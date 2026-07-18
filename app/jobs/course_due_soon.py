"""Daily cron: напоминание о дедлайне назначенного курса (Ф3a).

`course_assignments.due_at` в ближайшие 3 дня, курс published, курс ещё не
завершён (course_progress.completed_at IS NULL) → kind `course.due_soon`.
Анти-дуп: не чаще раза в 3 дня на пару (получатель, курс).

Скан — под bypass_rls (cross-tenant), доменная запись уведомлений — в
tenant-scoped сессии соответствующего тенанта (инвариант learn-домена:
bypass только на чтение очередей).

Run via systemd: `signaris-hub[-staging]-course-due-soon.timer` (daily).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.progress import CourseAssignment, CourseProgress

log = structlog.get_logger("jobs.course_due_soon")

DUE_WINDOW = timedelta(days=3)
ANTI_DUP_WINDOW = timedelta(days=3)


async def _already_reminded(session, course_id, employee_id, since) -> bool:  # noqa: ANN001
    row = await session.execute(
        sa_text(
            "SELECT 1 FROM notifications "
            "WHERE employee_id = :emp AND kind = 'course.due_soon' "
            "AND created_at > :since AND payload->>'course_id' = :cid LIMIT 1"
        ),
        {"emp": str(employee_id), "since": since, "cid": str(course_id)},
    )
    return row.scalar_one_or_none() is not None


async def main() -> int:
    log_config.configure()
    now = datetime.now(UTC)
    since = now - ANTI_DUP_WINDOW

    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        due = (
            await scan.execute(
                select(
                    CourseAssignment.course_id,
                    CourseAssignment.tenant_id,
                    CourseAssignment.due_at,
                    Course.title,
                    EmployeeProfile.employee_id,
                )
                .join(Course, Course.id == CourseAssignment.course_id)
                .join(
                    EmployeeProfile,
                    EmployeeProfile.id == CourseAssignment.profile_id,
                )
                .outerjoin(
                    CourseProgress,
                    (CourseProgress.course_id == CourseAssignment.course_id)
                    & (CourseProgress.profile_id == CourseAssignment.profile_id),
                )
                .where(
                    CourseAssignment.due_at.is_not(None),
                    CourseAssignment.due_at > now,
                    CourseAssignment.due_at <= now + DUE_WINDOW,
                    Course.status == "published",
                    CourseProgress.completed_at.is_(None),
                    EmployeeProfile.status == "active",
                    EmployeeProfile.employee_id.is_not(None),
                )
            )
        ).all()

    log.info("course_due_soon.scanned", due_count=len(due))
    sent = 0
    by_tenant: dict = {}
    for course_id, tenant_id, due_at, title, employee_id in due:
        by_tenant.setdefault(tenant_id, []).append((course_id, due_at, title, employee_id))

    from app.services.notification_dispatcher import dispatch

    for tenant_id, items in by_tenant.items():
        async with tenant_scoped_session(tenant_id) as session:
            for course_id, due_at, title, employee_id in items:
                if await _already_reminded(session, course_id, employee_id, since):
                    continue
                await dispatch(
                    session,
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    kind="course.due_soon",
                    title="Скоро дедлайн курса",
                    body=(
                        f"«{title}» — завершите до "
                        f"{due_at.astimezone(UTC).strftime('%d.%m.%Y')}."
                    ),
                    url=f"/learn/courses/{course_id}",
                    payload={"course_id": str(course_id)},
                )
                sent += 1
            await session.commit()

    log.info("course_due_soon.finished", sent=sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
