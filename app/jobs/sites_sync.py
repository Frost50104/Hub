"""Hourly cron: снимок реестра объектов auth + применение к `stores`.

До 19.09 снимок тянулся только ручной кнопкой («данные меняются ~4 раза в
год»). Решение владельца: реестр — источник истины про точки, закрытие и
открытие точки там ТРИГГЕРИТ автоматику в Hub — карточку магазина и состав
«Гусиной гонки». Поэтому:
1. `sync_sites()` — зеркало как было (модуль не менялся, `stores` не трогает);
2. `registry_apply.apply_registry` по каждому тенанту снимка, КРОМЕ занятых
   (try-лок другого прогона): план по старому зеркалу был бы планом по
   прошлому. Неполный/недоступный снимок — применения нет вовсе.
Гонка бежит в `:40` и подхватит новые карточки (`reconcile_participants`)
в тот же час. `SITES_SYNC_ENABLED=false` (staging) → только dry-run и выход.

Run via systemd: `signaris-hub[-staging]-sites-sync.timer` (`*:10`).
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.services.notify_batch import drain
from app.services.registry_apply import apply_registry
from app.services.sites_sync import sync_sites

log = structlog.get_logger("jobs.sites_sync")


async def main() -> int:
    log_config.configure()
    if not get_settings().sites_sync_enabled:
        report = await sync_sites(dry_run=True)
        log.info("sites_sync.disabled", available=report.available, sites=report.sites)
        return 0
    report = await sync_sites()
    if not report.available or report.total_mismatch:
        log.warning(
            "sites_sync.not_applied",
            available=report.available,
            total_mismatch=report.total_mismatch,
        )
        return 0
    for tenant_id in sorted(report.tenants - report.busy):
        try:
            async with tenant_scoped_session(UUID(tenant_id)) as session:
                rep = await apply_registry(session, UUID(tenant_id))
                await session.commit()
            log.info(
                "registry_apply.done",
                tenant_id=tenant_id,
                created=len(rep.created),
                archived=len(rep.archived),
                pending=rep.pending,
            )
        except Exception:  # noqa: BLE001 — один тенант не должен ронять остальные
            log.exception("registry_apply.tenant_failed", tenant_id=tenant_id)
    # Архив магазина шлёт уведомления новым членам аудиторий — дождаться хвоста.
    await drain()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
