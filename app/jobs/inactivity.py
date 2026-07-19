"""Daily cron: правило неактивности (Ф5, ТЗ §23). V1 без email (решение).

Механика по learning_settings (inactivity_warn_days / grace / текст):
1) тишина дольше warn_days → предупреждение сотруднику + руководителю
   (push+in-app, kind profile.inactivity), маркер inactivity_warned_at;
2) активность после предупреждения → маркер сбрасывается;
3) тишина дольше grace-периода после предупреждения → авто-архив через
   archive_profile (полный каскад: аудитории, автосценарии).

Run via systemd: `signaris-hub[-staging]-inactivity.timer` (daily).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, text

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile
from app.services.employee_profiles import archive_profile
from app.services.learn_notify import _employee_ids
from app.services.learn_settings import get_settings_dict
from app.services.notify_batch import notify_many

log = structlog.get_logger("jobs.inactivity")


async def _process_tenant(session, tenant_id) -> dict[str, int]:  # noqa: ANN001
    settings = await get_settings_dict(session, tenant_id)
    warn_days = int(settings.get("inactivity_warn_days") or 90)
    grace_days = int(settings.get("inactivity_archive_grace_days") or 3)
    warn_text = str(settings.get("inactivity_warn_text") or "").format(
        grace_days=grace_days
    )
    now = datetime.now(UTC)
    warn_threshold = now - timedelta(days=warn_days)

    profiles = (
        (
            await session.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.status == "active",
                    EmployeeProfile.employee_id.is_not(None),
                    EmployeeProfile.last_activity_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    stats = {"warned": 0, "reset": 0, "archived": 0}
    for profile in profiles:
        last = profile.last_activity_at
        warned = profile.inactivity_warned_at

        # Активность после предупреждения — сброс маркера.
        if warned is not None and last is not None and last > warned:
            profile.inactivity_warned_at = None
            stats["reset"] += 1
            continue

        if last is None or last > warn_threshold:
            continue  # активен в пределах порога

        if warned is None:
            profile.inactivity_warned_at = now
            stats["warned"] += 1
            recipients = [profile.id]
            if profile.manager_profile_id:
                recipients.append(profile.manager_profile_id)
            emp_map = await _employee_ids(session, recipients)
            # Сотруднику — текст-предупреждение; руководителю — контекст.
            if profile.id in emp_map:
                await notify_many(
                    session,
                    tenant_id=tenant_id,
                    employee_ids=[emp_map[profile.id]],
                    kind="profile.inactivity",
                    title="Аккаунт скоро уйдёт в архив",
                    body=warn_text,
                    url="/learn",
                )
            if profile.manager_profile_id and profile.manager_profile_id in emp_map:
                await notify_many(
                    session,
                    tenant_id=tenant_id,
                    employee_ids=[emp_map[profile.manager_profile_id]],
                    kind="profile.inactivity",
                    title="Сотрудник неактивен",
                    body=(
                        f"{profile.full_name} не заходил(а) в Hub дольше "
                        f"{warn_days} дней. Без активности аккаунт уйдёт в архив "
                        f"через {grace_days} дн."
                    ),
                    url="/learn/admin/employees",
                )
        elif warned < now - timedelta(days=grace_days):
            await archive_profile(
                session, profile, reason="auto_inactivity", actor_id=None
            )
            stats["archived"] += 1

    return stats


async def main() -> int:
    log_config.configure()
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_ids = [
            r[0]
            for r in await scan.execute(
                text(
                    "SELECT DISTINCT tenant_id FROM employee_profiles "
                    "WHERE status = 'active'"
                )
            )
        ]

    totals = {"warned": 0, "reset": 0, "archived": 0}
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(tenant_id) as session:
            stats = await _process_tenant(session, tenant_id)
            await session.commit()
            for key, value in stats.items():
                totals[key] += value

    log.info("inactivity.finished", tenants=len(tenant_ids), **totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
