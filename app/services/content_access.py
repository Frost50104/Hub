"""Контент-права learn-домена: author / publisher (hub-side, не JWT).

hub:admin эквивалентен publisher во всех проверках. Роль хранится в
employee_profiles.content_role, назначает её админ в карточке сотрудника.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.services.lifecycle import ContentRole, can


async def resolve_content_role(db: AsyncSession, principal: Principal) -> ContentRole:
    if principal.role_for("hub") == "admin":
        return "admin"
    row = (
        await db.execute(
            select(EmployeeProfile.content_role, EmployeeProfile.status).where(
                EmployeeProfile.employee_id == principal.employee_id
            )
        )
    ).one_or_none()
    if row is None or row[1] != "active":
        return "none"
    return row[0] if row[0] in ("author", "publisher") else "none"


async def require_content_role(
    db: AsyncSession, principal: Principal, need: str
) -> ContentRole:
    """403, если контент-роль ниже требуемой. Возвращает фактическую роль."""
    role = await resolve_content_role(db, principal)
    if not can(role, need):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нужны права на управление контентом — обратитесь к администратору",
        )
    return role
