"""Уведомления learn-домена (Ф1): обязательные ознакомления.

Два триггера `library.ack_required`:
1. публикация обязательного материала → вся текущая аудитория;
2. hook «вступил в аудиторию» (granted_at): пересчёт членства добавил
   людей → уведомить о pending обязательных материалах этой аудитории
   (поздно нанятый сотрудник иначе не узнал бы о документе никогда —
   adversarial-ревью плана §6).

Получатели маппятся profile → employee_id; карточки без входа (employee_id
NULL) молча пропускаются — уведомлять некого. Фан-аут последовательный —
на масштабе Ф1 достаточно (батч-диспетчер придёт в Ф2 с news.published).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.library import LibraryMaterial, MaterialAcknowledgement
from app.models.progress import CourseProgress
from app.services.audience_resolver import MembershipDiff
from app.services.notify_batch import notify_many

log = structlog.get_logger("learn_notify")


def _material_url(material: LibraryMaterial) -> str:
    return f"/learn/library?m={material.id}"


async def _employee_ids(
    db: AsyncSession, profile_ids: list[UUID]
) -> dict[UUID, UUID]:
    """profile_id → employee_id (только активные и с привязанным входом)."""
    if not profile_ids:
        return {}
    rows = await db.execute(
        select(EmployeeProfile.id, EmployeeProfile.employee_id).where(
            EmployeeProfile.id.in_(profile_ids),
            EmployeeProfile.employee_id.is_not(None),
            EmployeeProfile.status == "active",
        )
    )
    return {r[0]: r[1] for r in rows}


async def notify_ack_required(
    db: AsyncSession, material: LibraryMaterial, profile_ids: list[UUID]
) -> int:
    """Разослать library.ack_required списку профилей. → сколько отправлено."""
    recipients = await _employee_ids(db, profile_ids)
    return await notify_many(
        db,
        tenant_id=material.tenant_id,
        employee_ids=list(recipients.values()),
        kind="library.ack_required",
        title="Требуется ознакомление",
        body=f"«{material.title}» — подтвердите ознакомление с документом.",
        url=_material_url(material),
        payload={"material_id": str(material.id)},
    )


async def notify_new_audience_members(
    db: AsyncSession, diffs: dict[UUID, MembershipDiff]
) -> None:
    """Hook granted_at: новым членам аудиторий — pending обязательные материалы."""
    added_by_audience = {
        audience_id: diff.added for audience_id, diff in diffs.items() if diff.added
    }
    if not added_by_audience:
        return

    materials = (
        (
            await db.execute(
                select(LibraryMaterial).where(
                    LibraryMaterial.audience_id.in_(added_by_audience.keys()),
                    LibraryMaterial.status == "published",
                    LibraryMaterial.requires_acknowledgement.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for material in materials:
        profile_ids = added_by_audience.get(material.audience_id, [])
        if not profile_ids:
            continue
        # Не шуметь тем, кто уже подтверждал (re-add в аудиторию).
        acked = {
            r[0]
            for r in await db.execute(
                select(MaterialAcknowledgement.profile_id).where(
                    MaterialAcknowledgement.material_id == material.id,
                    MaterialAcknowledgement.profile_id.in_(profile_ids),
                )
            )
        }
        fresh = [pid for pid in profile_ids if pid not in acked]
        sent = await notify_ack_required(db, material, fresh)
        if sent:
            log.info(
                "learn_notify.ack_on_grant",
                material_id=str(material.id),
                sent=sent,
            )

    # Mandatory-курсы (Ф3a): поздно вошедший в аудиторию обязан узнать
    # о курсе так же, как о документе на ознакомление.
    courses = (
        (
            await db.execute(
                select(Course).where(
                    Course.audience_id.in_(added_by_audience.keys()),
                    Course.status == "published",
                    Course.course_type == "mandatory",
                )
            )
        )
        .scalars()
        .all()
    )
    for course in courses:
        profile_ids = added_by_audience.get(course.audience_id, [])
        if not profile_ids:
            continue
        # Уже завершившим курс (re-add в аудиторию) — не шуметь.
        done = {
            r[0]
            for r in await db.execute(
                select(CourseProgress.profile_id).where(
                    CourseProgress.course_id == course.id,
                    CourseProgress.profile_id.in_(profile_ids),
                    CourseProgress.completed_at.is_not(None),
                )
            )
        }
        fresh = [pid for pid in profile_ids if pid not in done]
        recipients = await _employee_ids(db, fresh)
        sent = await notify_many(
            db,
            tenant_id=course.tenant_id,
            employee_ids=list(recipients.values()),
            kind="course.assigned",
            title=course.title,
            body="Вам назначен обязательный курс.",
            url=f"/learn/courses/{course.id}",
            payload={"course_id": str(course.id)},
        )
        if sent:
            log.info(
                "learn_notify.course_on_grant",
                course_id=str(course.id),
                sent=sent,
            )
