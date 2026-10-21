"""Скоуп руководителя (Ф0 LMS): «по кому видна аналитика/отчёты/сотрудники».

НЕ путать с audience (тот решает «что видно как потребителю контента»):
- hub:admin → весь tenant;
- ТУ → сотрудники/отчёты только своих магазинов (tu_store_assignments);
- владелец франчайзи → магазины своего франчайзи;
- остальные → только о себе.

Единая точка для learn-аналитики, отчётов об ознакомлении и списков
сотрудников (Ф1+).

Права по данным карточки (контур, франчайзи, точки ТУ, контент-роль) даёт
только `card_grants_rights` — у кассы (общего логина точки) их нет, даже если
копия на карточке осталась (HUB_TASK_account_kind_switch, 21.10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
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


def card_grants_rights(profile: Any, principal: Principal | None = None) -> bool:
    """Права по данным карточки — контур, франчайзи, точки ТУ, контент-роль —
    только у АКТИВНОЙ карточки ЧЕЛОВЕКА.

    Касса (`account_kind='service'`, общий логин планшета точки) их не
    получает, даже если копия на карточке осталась: смена вида в T2 меняет
    только вид, а T3 кассы пропускает — у бывшего «Офиса» сохранились бы
    отчёты iiko по сети (HUB_TASK_account_kind_switch, 21.10). Копию не
    стираем — решение владельца: под этим правилом она ничего не даёт.

    Источник вида — карточка: выгрузка штата главнее claim'а, и вид
    существующей карточки claim не меняет никогда. Claim токена здесь умеет
    ТОЛЬКО запретить: свежий токен уже «service», а синк штата не дошёл или
    лежит. `getattr` — код переживает откат либы (claim'а нет → «не знаю»).

    Принимает ORM-объект и `Row` с теми же именами колонок. `None` и
    незнакомый вид — отказ. Не путать с `learning_population_filter`: тот
    про «кто учится», и разойтись им можно.
    """
    if getattr(principal, "account_kind", None) == "service":
        return False
    return (
        profile is not None
        and profile.status == "active"
        and profile.account_kind == "person"
    )


def effective_org_role(profile: Any, principal: Principal | None = None) -> str:
    """Контур, который ДАЁТ ПРАВА; у кассы и архивной карточки — `employee`.

    Данные карточки не трогает: это ответ на вопрос «что можно», а не «что
    записано»."""
    return profile.org_role if card_grants_rights(profile, principal) else "employee"


def effective_content_role(profile: Any, principal: Principal | None = None) -> str:
    """Контент-роль, которая ДАЁТ ПРАВА; у кассы и архивной карточки — `none`."""
    if not card_grants_rights(profile, principal):
        return "none"
    return profile.content_role if profile.content_role in ("author", "publisher") else "none"


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
    if not card_grants_rights(profile, principal):
        # Касса: скоупа руководителя нет, но своя карточка — своя
        # (profile_id обязателен, иначе касса получит 404 на себя).
        return Scope(kind="self", profile_id=profile.id)

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
