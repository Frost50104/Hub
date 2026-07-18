"""Сертификаты о прохождении курса (Ф3b, ТЗ §4.5).

V1 = страница + браузерная печать (решение плана). Выдача идемпотентна —
UNIQUE(course_id, profile_id); снапшот названия курса и имени сотрудника
фиксируется на момент выдачи и не меняется при переименованиях.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Certificate
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile

log = structlog.get_logger("certificate")


def _serial() -> str:
    year = datetime.now(UTC).year
    return f"HUB-{year}-{secrets.token_hex(4).upper()}"


async def issue_if_earned(
    db: AsyncSession, course: Course, profile: EmployeeProfile
) -> bool:
    """Выдать сертификат за завершённый курс (если включён). → выдан ли новый."""
    if not course.certificate_enabled:
        return False
    # Коллизия serial внутри tenant'а астрономически маловероятна (4 байта
    # hex на год), но ON CONFLICT по (course, profile) идемпотентит повторы.
    stmt = pg_insert(Certificate).values(
        tenant_id=course.tenant_id,
        profile_id=profile.id,
        course_id=course.id,
        serial=_serial(),
        course_title=course.title,
        full_name=profile.full_name,
    )
    result = await db.execute(
        stmt.on_conflict_do_nothing(index_elements=["course_id", "profile_id"])
    )
    issued = bool(result.rowcount)
    if issued:
        log.info("certificate.issued", course_id=str(course.id), profile_id=str(profile.id))
    return issued
