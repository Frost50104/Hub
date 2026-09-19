"""«Гусиная гонка»: ночное закрытие дня (systemd timer, 00:45 UTC = 03:45 MSK).

`close_day = вчера` по московской дате. На тенант:
1. `pull_days([close_day − 1, close_day])` — учётный день iiko закрыт, чеки
   после полуночи уже легли; `IikoBusy` — одна повторная попытка через 60 с,
   иначе снимки догонит следующая ночь (`pending_snapshot_days`);
2. `close_day` для активных конкурсов: снимки, итоги заезда по `ends_on`,
   следующий заезд; commit;
3. если следующему заезду нужна база (режим `race`) — `compute_baselines`
   ОТДЕЛЬНО, вне advisory-лока: расчёт ходит в iiko;
4. `last_close_day` в `race_sync_state`.
Пушей здесь нет — их шлёт часовая джоба после 09:00.

Гейты те же, что у race_sync: без них staging тянул бы iiko и двигал
конкурсы, а окружение без кредов падало бы в `failed` каждую ночь.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
from sqlalchemy import select, text

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.race import Race, RaceContest
from app.redis_client import close_redis
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.race import engine, gate, iiko_pull

log = structlog.get_logger("jobs.race_close")

_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM race_contests WHERE status IN ('scheduled', 'active')"
)
RETRY_SLEEP_SEC = 60.0


async def _pull_with_retry(session, tenant_id, *, close_day) -> bool:
    for attempt in (1, 2):
        try:
            await iiko_pull.pull_days(
                session,
                tenant_id=tenant_id,
                day_from=close_day - timedelta(days=1),
                day_to=close_day,
            )
            return True
        except iiko_service.IikoBusy:
            log.info("race_close.busy", tenant_id=str(tenant_id), attempt=attempt)
            if attempt == 1:
                await asyncio.sleep(RETRY_SLEEP_SEC)
        except (IikoError, IikoNotConfigured) as e:
            log.warning("race_close.pull_failed", tenant_id=str(tenant_id), err=str(e))
            return False
    return False


async def _tenant_close(tenant_id, *, close_day, today) -> None:
    async with tenant_scoped_session(tenant_id) as session:
        if not await gate.tenant_enabled(session, tenant_id):
            log.info("race_close.tenant_disabled", tenant_id=str(tenant_id))
            return
        pulled = await _pull_with_retry(session, tenant_id, close_day=close_day)
        await session.commit()
        needing_baseline: list = []
        contests = list(
            (
                await session.execute(
                    select(RaceContest).where(
                        RaceContest.tenant_id == tenant_id, RaceContest.status == "active"
                    )
                )
            ).scalars()
        )
        for contest in contests:
            report = await engine.close_day(session, contest, close_day=close_day)
            await session.commit()
            log.info(
                "race_close.closed",
                tenant_id=str(tenant_id),
                contest_id=str(contest.id),
                snapshots=report.snapshots,
                finished=[str(r) for r in report.finished_race_ids],
                activated=[str(r) for r in report.activated_race_ids],
                contest_finished=report.contest_finished,
                pulled=pulled,
            )
            for race_id in report.races_needing_baseline:
                needing_baseline.append((contest.id, race_id))
        for contest_id, race_id in needing_baseline:
            contest = await session.get(RaceContest, contest_id)
            race = await session.get(Race, race_id)
            try:
                rep = await iiko_pull.compute_baselines(session, contest=contest, race=race)
                await session.commit()
                log.info(
                    "race_close.baselines",
                    contest_id=str(contest_id),
                    race_id=str(race_id),
                    computed=rep.computed,
                    empty=rep.empty,
                )
            except (iiko_service.IikoBusy, IikoError, IikoNotConfigured) as e:
                await session.rollback()
                log.warning("race_close.baselines_failed", race_id=str(race_id), err=str(e))
        await engine.activate_due(session, tenant_id, today=today)
        await iiko_pull.touch_sync_state(session, tenant_id, close_day=close_day)
        await session.commit()


async def main() -> int:
    log_config.configure()
    settings = get_settings()
    if not settings.race_enabled or not settings.race_sync_enabled:
        log.info("race_close.disabled")
        return 0
    if not iiko_service.is_configured():
        log.info("race_close.iiko_not_configured")
        return 0
    today = engine.today_local()
    close_day = today - timedelta(days=1)
    try:
        async with tenant_scoped_session(None, bypass_rls=True) as scan:
            tenant_ids = [r[0] for r in await scan.execute(_TENANTS_SQL)]
        log.info("race_close.started", tenants=len(tenant_ids), close_day=str(close_day))
        for tenant_id in tenant_ids:
            try:
                await _tenant_close(tenant_id, close_day=close_day, today=today)
            except Exception:  # noqa: BLE001
                log.exception("race_close.tenant_failed", tenant_id=str(tenant_id))
        log.info("race_close.finished")
    finally:
        await close_redis()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
