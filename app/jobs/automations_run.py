"""Hourly cron: исполнение welcome-автосценариев (Ф5, ТЗ §22).

Сканер (а не хуки в ручках): находит профили, подходящие под enabled-правила,
материализует jobs (UNIQUE rule+profile — повторные прогоны не дублируют)
и исполняет их чанком ≤200 за прогон (не шторм пушей). Ретро-защита:
только профили, созданные ПОСЛЕ rule.applies_from.

Скан тенантов — bypass, доменная запись — в tenant-scoped сессиях.
Run via systemd: `signaris-hub[-staging]-automations.timer` (hourly).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.automation import AutomationJob, AutomationRule
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.progress import CourseAssignment
from app.services.learn_notify import _employee_ids
from app.services.notify_batch import notify_many

log = structlog.get_logger("jobs.automations")

CHUNK = 200


async def _materialize(session, rule: AutomationRule) -> int:  # noqa: ANN001
    """Создать pending-jobs для новых подходящих профилей. → сколько создано."""
    stmt = select(EmployeeProfile.id).where(
        EmployeeProfile.status == "active",
        EmployeeProfile.employee_id.is_not(None),  # активирован = входил
        EmployeeProfile.created_at >= rule.applies_from,
    )
    if rule.trigger == "position_assigned":
        if rule.position_ids:
            stmt = stmt.where(EmployeeProfile.position_id.in_(rule.position_ids))
        else:
            stmt = stmt.where(EmployeeProfile.position_id.is_not(None))
    candidate_ids = [r[0] for r in await session.execute(stmt)]
    created = 0
    for profile_id in candidate_ids:
        result = await session.execute(
            pg_insert(AutomationJob)
            .values(
                tenant_id=rule.tenant_id,
                rule_id=rule.id,
                profile_id=profile_id,
                course_id=rule.course_id,
                due_at=(
                    datetime.now(UTC) + timedelta(days=rule.due_days)
                    if rule.due_days
                    else None
                ),
            )
            .on_conflict_do_nothing(constraint="uq_automation_jobs_rule_profile")
        )
        created += result.rowcount or 0
    return created


async def _execute_pending(session, tenant_id) -> int:  # noqa: ANN001
    """Исполнить чанк pending-jobs: назначить курс + уведомить. → сколько."""
    jobs = (
        (
            await session.execute(
                select(AutomationJob)
                .where(AutomationJob.status == "pending")
                .order_by(AutomationJob.created_at)
                .limit(CHUNK)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not jobs:
        return 0

    courses = {
        c.id: c
        for c in (
            await session.execute(
                select(Course).where(Course.id.in_({j.course_id for j in jobs}))
            )
        )
        .scalars()
        .all()
    }
    executed = 0
    notify_by_course: dict = {}
    for job in jobs:
        course = courses.get(job.course_id)
        if course is None:  # курс удалён — job отменяется
            job.status = "cancelled"
            continue
        await session.execute(
            pg_insert(CourseAssignment)
            .values(
                course_id=job.course_id,
                profile_id=job.profile_id,
                tenant_id=job.tenant_id,
                source="automation",
                due_at=job.due_at,
            )
            .on_conflict_do_update(
                index_elements=["course_id", "profile_id"],
                set_={"due_at": job.due_at},
            )
        )
        job.status = "done"
        job.executed_at = datetime.now(UTC)
        executed += 1
        if course.status == "published":
            notify_by_course.setdefault(course, []).append(job.profile_id)

    for course, profile_ids in notify_by_course.items():
        recipients = await _employee_ids(session, profile_ids)
        await notify_many(
            session,
            tenant_id=tenant_id,
            employee_ids=list(recipients.values()),
            kind="course.assigned",
            title=course.title,
            body="Вам назначен курс — начните обучение.",
            url=f"/learn/courses/{course.id}",
            payload={"course_id": str(course.id)},
        )
    return executed


async def main() -> int:
    log_config.configure()
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_ids = [
            r[0]
            for r in await scan.execute(
                text("SELECT DISTINCT tenant_id FROM automation_rules WHERE enabled")
            )
        ]

    total_created = total_executed = 0
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(tenant_id) as session:
            rules = (
                (
                    await session.execute(
                        select(AutomationRule).where(AutomationRule.enabled.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            for rule in rules:
                total_created += await _materialize(session, rule)
            total_executed += await _execute_pending(session, tenant_id)
            await session.commit()

    log.info(
        "automations.finished",
        tenants=len(tenant_ids),
        jobs_created=total_created,
        jobs_executed=total_executed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
