"""«Гусиная гонка»: часовая дотяжка чеков iiko + пуши (systemd timer, *:40).

Порядок тика на тенант с scheduled/active конкурсом:
1. `activate_due` — запланированное со стартом ≤ сегодня становится активным;
2. при активном конкурсе — `pull_days([вчера, сегодня])` (одна сессия iiko под
   fenced-локом); `IikoBusy` — пропустить тик, следующий через час;
3. commit;
4. `send_pending_notifications` — в отдельной сессии, метки дедупа коммитятся
   до отправки; не раньше 09:00 MSK;
5. `drain()` — дождаться фоновых пуш-задач с потолком (иначе `asyncio.run`
   отменит хвост рассылки).

Гейты: `race_enabled` (модуль), `race_sync_enabled` (iiko + пуши; staging —
false), `iiko_service.is_configured()`, тенантный тумблер.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.redis_client import close_redis
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.notify_batch import drain
from app.services.race import engine, gate, iiko_pull, read

log = structlog.get_logger("jobs.race_sync")

_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM race_contests WHERE status IN ('scheduled', 'active')"
)


async def _tenant_tick(tenant_id, *, today) -> None:
    async with tenant_scoped_session(tenant_id) as session:
        if not await gate.tenant_enabled(session, tenant_id):
            log.info("race_sync.tenant_disabled", tenant_id=str(tenant_id))
            return
        await engine.activate_due(session, tenant_id, today=today)
        await session.commit()
        active = await read.current_contest(session, tenant_id)
        if active is None or active.status != "active":
            return
        # Состав против Оргструктуры ДО выгрузки: при занятом iiko новая точка
        # и закрытая всё равно обновляются в этот час.
        await engine.reconcile_participants(session, active)
        await session.commit()
        try:
            report = await iiko_pull.pull_days(
                session,
                tenant_id=tenant_id,
                day_from=today - timedelta(days=1),
                day_to=today,
            )
            log.info(
                "race_sync.pulled",
                tenant_id=str(tenant_id),
                rows=report.rows,
                departments=report.departments,
                skipped_empty=report.skipped_empty,
            )
        except iiko_service.IikoBusy:
            log.info("race_sync.busy_skip", tenant_id=str(tenant_id))
        except (IikoError, IikoNotConfigured) as e:
            log.warning("race_sync.pull_failed", tenant_id=str(tenant_id), err=str(e))
        await session.commit()


async def main() -> int:
    log_config.configure()
    settings = get_settings()
    if not settings.race_enabled or not settings.race_sync_enabled:
        log.info("race_sync.disabled")
        return 0
    if not iiko_service.is_configured():
        log.info("race_sync.iiko_not_configured")
        return 0
    today = engine.today_local()
    try:
        async with tenant_scoped_session(None, bypass_rls=True) as scan:
            tenant_ids = [r[0] for r in await scan.execute(_TENANTS_SQL)]
        log.info("race_sync.started", tenants=len(tenant_ids), today=str(today))
        sent_total = 0
        for tenant_id in tenant_ids:
            try:
                await _tenant_tick(tenant_id, today=today)
                sent_total += await engine.send_pending_notifications(
                    tenant_id, now=datetime.now(UTC)
                )
            except Exception:  # noqa: BLE001 — один тенант не должен ронять остальные
                log.exception("race_sync.tenant_failed", tenant_id=str(tenant_id))
        cancelled = await drain()
        log.info("race_sync.finished", sent=sent_total, push_cancelled=cancelled)
    finally:
        await close_redis()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
