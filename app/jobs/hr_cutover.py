"""Окно каткатa кадровых данных (16d, часть C) — единственный писатель `cutover_freeze`.

    python -m app.jobs.hr_cutover --status
    python -m app.jobs.hr_cutover --tenant uppetit --window open
    python -m app.jobs.hr_cutover --tenant uppetit --window close
    python -m app.jobs.hr_cutover --tenant uppetit --force-unfreeze

Окно — ручная заморозка правки кадров в Hub на время переноса: от второй
выгрузки до первого применения. Воркер синка это поле не трогает, поэтому
окно обязательно закрывать руками (шаг 6.9 плана выката; алерт через 6 часов).

`--force-unfreeze` — аварийный рычаг: auth недоступен долго, а править надо.
Снимает заморозку до следующего ПОЛНОГО снимка справочников — если auth всё
ещё ведёт кадры организации, первый же прогон заморозит её снова.

Каждое действие — запись в журнал (`hr_window` / `hr_unfreeze`) и печать
итогового состояния: заморожен, ведёт ли auth, применяется ли, отложенный
набор, последнее применение, флаг потребителя.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.hr_sync import HrSyncState
from app.models.shadow import ShadowTenant
from app.services import audit, hr_state


def _say(text: str) -> None:
    """Вывод для человека у консоли (журнал — отдельно, через audit)."""
    sys.stdout.write(text + "\n")


async def _tenants() -> dict[str, UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        rows = await db.execute(select(ShadowTenant.slug, ShadowTenant.id))
        return dict(rows.tuples().all())


def _describe(slug: str, state: HrSyncState | None) -> list[str]:
    settings = get_settings()
    applying = hr_state.tenant_applies(slug, settings.hr_apply_tenant_slugs)
    if state is None:
        return [f"{slug}: строки состояния нет — потребитель ещё не видел организацию"]
    now = datetime.now(UTC)
    view = hr_state.derive_view(
        state, applying=applying, now=now, interval_sec=settings.staff_sync_interval_sec
    )
    lines = [
        f"{slug}:",
        f"  заморожен: {'да' if view.frozen else 'нет'} (состояние: {view.state or '—'})",
        f"  auth ведёт кадры (authoritative): {'да' if state.authoritative else 'нет'}"
        f", в снимке: {'да' if state.in_snapshot else 'нет'}, снимок: {state.snapshot_at}",
        "  окно каткатa: "
        + (f"ОТКРЫТО с {state.cutover_since}" if state.cutover_freeze else "закрыто"),
        f"  применяется (в SIGNARIS_HUB_HR_APPLY_TENANTS): {'да' if applying else 'нет'}",
        f"  последний прогон: {state.last_run_at} ({state.last_mode or '—'}),"
        f" последнее применение: {state.last_applied_at}",
    ]
    if state.pending_fingerprint:
        lines.append(
            f"  ОТЛОЖЕННЫЙ НАБОР с {state.pending_since}: {state.blocked_reason}"
            f" (отпечаток {state.pending_fingerprint[:12]}…)"
        )
    if not settings.hr_consumer_enabled:
        lines.append(
            "  ⚠ SIGNARIS_HUB_HR_CONSUMER_ENABLED=false — состояние НЕ обновляется, "
            "заморозка держится последним известным"
        )
    return lines


async def _status() -> int:
    tenants = await _tenants()
    for slug, tenant_id in sorted(tenants.items()):
        async with tenant_scoped_session(tenant_id) as db:
            state = await hr_state.load_state(db, tenant_id)
            _say("\n".join(_describe(slug, state)))
    return 0


async def _change(slug: str, *, window: str | None, force_unfreeze: bool) -> int:
    tenants = await _tenants()
    tenant_id = tenants.get(slug)
    if tenant_id is None:
        _say(f"Организация «{slug}» не найдена в shadow_tenants")
        return 2
    now = datetime.now(UTC)
    async with tenant_scoped_session(tenant_id) as db:
        await db.execute(
            pg_insert(HrSyncState)
            .values(tenant_id=tenant_id)
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        state = await db.get(HrSyncState, tenant_id, with_for_update=True, populate_existing=True)
        assert state is not None
        if window is not None:
            opening = window == "open"
            old = state.cutover_freeze
            state.cutover_freeze = opening
            state.cutover_since = now if opening else None
            action, diff = "hr_window", {"cutover_freeze": {"old": old, "new": opening}}
        else:
            old = state.authoritative
            state.authoritative = False
            state.in_snapshot = False
            state.authoritative_since = None
            action, diff = "hr_unfreeze", {"authoritative": {"old": old, "new": False}}
        state.updated_at = now
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_id=None,
            action=action,
            object_type="hr_sync",
            object_label="Кадровые данные из auth",
            diff=diff,
        )
        await db.commit()
        _say("\n".join(_describe(slug, state)))
    if force_unfreeze:
        _say(
            "⚠ Заморозка снята до следующего ПОЛНОГО снимка справочников: если auth "
            "всё ещё ведёт кадры организации, ближайший прогон синка заморозит её снова."
        )
    if window == "close" and state.authoritative and not hr_state.tenant_applies(
        slug, get_settings().hr_apply_tenant_slugs
    ):
        _say(
            "⚠ Окно закрыто, но организация заморожена и НЕ в SIGNARIS_HUB_HR_APPLY_TENANTS: "
            "правки из auth в Hub не приходят, а в Hub их не сделать."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Окно каткатa кадровых данных из auth (16d)")
    parser.add_argument("--status", action="store_true", help="состояние всех организаций")
    parser.add_argument("--tenant", help="slug организации")
    parser.add_argument("--window", choices=("open", "close"), help="открыть/закрыть окно")
    parser.add_argument(
        "--force-unfreeze",
        action="store_true",
        help="аварийно снять заморозку до следующего полного снимка",
    )
    args = parser.parse_args(argv)
    log_config.configure()
    if args.status:
        return asyncio.run(_status())
    if not args.tenant or (args.window is None) == (not args.force_unfreeze):
        parser.error("нужно --status, либо --tenant вместе с ОДНИМ из --window / --force-unfreeze")
    return asyncio.run(
        _change(args.tenant, window=args.window, force_unfreeze=args.force_unfreeze)
    )


if __name__ == "__main__":
    raise SystemExit(main())
