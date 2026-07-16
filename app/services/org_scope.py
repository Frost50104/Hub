"""Скоуп руководителя (Ф0 LMS): «по кому видна аналитика/отчёты/сотрудники».

НЕ путать с audience (тот решает «что видно как потребителю контента»):
- hub:admin → весь tenant;
- ТУ → сотрудники/отчёты только своих магазинов (tu_store_assignments);
- владелец франчайзи → магазины своего франчайзи;
- остальные → только о себе.

Единая точка для learn-аналитики, отчётов об ознакомлении и списков
сотрудников (Ф1+).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Store


@dataclass(frozen=True)
class Scope:
    kind: Literal["all", "stores", "self"]
    store_ids: frozenset[UUID] = frozenset()
    profile_id: UUID | None = None


async def get_profile(db: AsyncSession, principal: Principal) -> EmployeeProfile | None:
    """Профиль текущего пользователя (привязка по employee_id)."""
    return (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.employee_id == principal.employee_id)
        )
    ).scalar_one_or_none()


async def resolve_scope(db: AsyncSession, principal: Principal) -> Scope:
    if principal.role_for("hub") == "admin":
        return Scope(kind="all")

    profile = await get_profile(db, principal)
    if profile is None or profile.status != "active":
        return Scope(kind="self")

    if profile.org_role == "tu":
        store_ids = {
            row[0]
            for row in await db.execute(
                select(TuStoreAssignment.store_id).where(
                    TuStoreAssignment.profile_id == profile.id
                )
            )
        }
        return Scope(kind="stores", store_ids=frozenset(store_ids), profile_id=profile.id)

    if profile.org_role == "franchisee_owner" and profile.franchisee_id:
        store_ids = {
            row[0]
            for row in await db.execute(
                select(Store.id).where(
                    Store.franchisee_id == profile.franchisee_id,
                    Store.archived_at.is_(None),
                )
            )
        }
        return Scope(kind="stores", store_ids=frozenset(store_ids), profile_id=profile.id)

    return Scope(kind="self", profile_id=profile.id)
