"""Integration-тесты Ф0: пересчёт audience_members + матчинг профилей (реальный PG).

Закрывают DB-зависимые находки ревью: diff-пересчёт сохраняет granted_at,
перевод сотрудника мгновенно меняет членство, повторный найм не создаёт
дубль, архивация вычищает членства, восстановление возвращает.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.services.audience_resolver import recalc_audience, recalc_profile
from app.services.employee_profiles import (
    archive_profile,
    ensure_profile_for_principal,
    restore_profile,
)
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _mk_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    position_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
) -> EmployeeProfile:
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        email=email,
        full_name=email.split("@")[0],
        position_id=position_id,
        store_id=store_id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _members(db: AsyncSession, audience_id: uuid.UUID) -> dict[uuid.UUID, object]:
    rows = await db.execute(
        select(AudienceMember.profile_id, AudienceMember.granted_at).where(
            AudienceMember.audience_id == audience_id
        )
    )
    return {r[0]: r[1] for r in rows}


async def test_recalc_diff_preserves_granted_at(db: AsyncSession, tenant_id: uuid.UUID):
    pos_seller = Position(tenant_id=tenant_id, name="Продавец")
    pos_admin = Position(tenant_id=tenant_id, name="Администратор")
    db.add_all([pos_seller, pos_admin])
    await db.flush()

    seller = await _mk_profile(db, tenant_id, email="s@t.ru", position_id=pos_seller.id)
    admin = await _mk_profile(db, tenant_id, email="a@t.ru", position_id=pos_admin.id)

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[pos_seller.id],
        )
    )
    await db.flush()

    diff = await recalc_audience(db, audience)
    assert diff.added == [seller.id]
    first = await _members(db, audience.id)
    assert set(first) == {seller.id}

    # Расширяем правило на администраторов: продавец остаётся с ИСХОДНЫМ
    # granted_at (diff/upsert, не truncate).
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[pos_admin.id],
        )
    )
    await db.flush()
    diff = await recalc_audience(db, audience)
    assert diff.added == [admin.id] and not diff.removed
    second = await _members(db, audience.id)
    assert second[seller.id] == first[seller.id]
    assert set(second) == {seller.id, admin.id}


async def test_profile_transfer_updates_membership(db: AsyncSession, tenant_id: uuid.UUID):
    store_a = Store(tenant_id=tenant_id, name="П14")
    store_b = Store(tenant_id=tenant_id, name="Л15")
    db.add_all([store_a, store_b])
    await db.flush()
    employee = await _mk_profile(db, tenant_id, email="e@t.ru", store_id=store_a.id)

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            store_ids=[store_a.id],
        )
    )
    await db.flush()
    await recalc_audience(db, audience)
    assert set(await _members(db, audience.id)) == {employee.id}

    # Перевод в другой магазин: «доступы меняются автоматически» (ТЗ §2.1).
    employee.store_id = store_b.id
    await db.flush()
    await recalc_profile(db, employee)
    assert set(await _members(db, audience.id)) == set()


async def test_matching_link_create_and_rehire(db: AsyncSession, tenant_id: uuid.UUID):
    # Карточка заведена HR заранее (регистр email нарочно другой).
    card = await _mk_profile(db, tenant_id, email="maria.ivanova@uppetit.ru")

    principal = make_principal(tenant_id, email="Maria.Ivanova@UPPETIT.ru")
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")

    result = await ensure_profile_for_principal(db, principal)
    assert result.outcome == "linked"
    assert result.profile is not None and result.profile.id == card.id
    assert result.profile.employee_id == principal.employee_id

    # Повторный вход — идемпотентно.
    result = await ensure_profile_for_principal(db, principal)
    assert result.outcome == "already_linked"

    # Неизвестный email → авто-создание минимальной карточки.
    stranger = make_principal(tenant_id, email="new@uppetit.ru", full_name="Новый")
    await upsert_shadow_user(db, stranger, table="shadow_users")
    result = await ensure_profile_for_principal(db, stranger)
    assert result.outcome == "created"
    assert result.profile is not None and result.profile.email == "new@uppetit.ru"

    # Повторный найм: карточка в архиве, у человека НОВЫЙ employee_id —
    # дубль не создаётся, требуется restore.
    await archive_profile(db, card, reason="manual", actor_id=None)
    rehired = make_principal(tenant_id, email="maria.ivanova@uppetit.ru")
    await upsert_shadow_user(db, rehired, table="shadow_users")
    result = await ensure_profile_for_principal(db, rehired)
    assert result.outcome == "needs_restore"
    assert result.profile is not None and result.profile.id == card.id

    # Restore с перепривязкой на новый вход.
    await restore_profile(db, card, actor_id=None, new_employee_id=rehired.employee_id)
    assert card.status == "active" and card.employee_id == rehired.employee_id


async def test_archive_cascade_removes_membership(db: AsyncSession, tenant_id: uuid.UUID):
    employee = await _mk_profile(db, tenant_id, email="x@t.ru")
    audience = Audience(tenant_id=tenant_id, is_all=True)
    db.add(audience)
    await db.flush()
    await recalc_audience(db, audience)
    assert set(await _members(db, audience.id)) == {employee.id}

    await archive_profile(db, employee, reason="manual", actor_id=None)
    assert set(await _members(db, audience.id)) == set()

    await restore_profile(db, employee, actor_id=None)
    assert set(await _members(db, audience.id)) == {employee.id}
