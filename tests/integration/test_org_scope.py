"""Integration-тесты скоупов руководителей (org_scope) — реальный PG.

Закрывают «не-админские скоупы» без второго SSO-аккаунта: Principal — просто
датакласс, подписи JWT на сервисном уровне не нужны. HTTP-обвязка
(require_auth) — общая инфраструктура, проверенная в проде.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Franchisee, Store
from app.services.employee_profiles import archive_profile
from app.services.org_scope import resolve_scope
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _profile_for(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    role: str = "member",
    **fields,
):
    principal = make_principal(tenant_id, email=email, role=role)
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=principal.employee_id,
        email=email,
        full_name=email.split("@")[0],
        **fields,
    )
    db.add(profile)
    await db.flush()
    return principal, profile


async def test_admin_scope_is_all(db: AsyncSession, tenant_id: uuid.UUID):
    principal, _ = await _profile_for(db, tenant_id, email="boss@t.ru", role="admin")
    scope = await resolve_scope(db, principal)
    assert scope.kind == "all"


async def test_member_without_profile_is_self(db: AsyncSession, tenant_id: uuid.UUID):
    principal = make_principal(tenant_id, email="ghost@t.ru")
    scope = await resolve_scope(db, principal)
    assert scope.kind == "self" and scope.profile_id is None


async def test_regular_employee_scope_is_self(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _profile_for(db, tenant_id, email="seller@t.ru")
    scope = await resolve_scope(db, principal)
    assert scope.kind == "self" and scope.profile_id == profile.id


async def test_tu_scope_is_assigned_stores(db: AsyncSession, tenant_id: uuid.UUID):
    store_a = Store(tenant_id=tenant_id, name="П14")
    store_b = Store(tenant_id=tenant_id, name="Л15")
    store_other = Store(tenant_id=tenant_id, name="В30")
    db.add_all([store_a, store_b, store_other])
    await db.flush()

    principal, tu = await _profile_for(db, tenant_id, email="tu@t.ru", org_role="tu")
    db.add_all(
        [
            TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=store_a.id),
            TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=store_b.id),
        ]
    )
    await db.flush()

    scope = await resolve_scope(db, principal)
    assert scope.kind == "stores"
    assert scope.store_ids == frozenset({store_a.id, store_b.id})
    assert store_other.id not in scope.store_ids


async def test_franchisee_owner_scope_is_his_stores(db: AsyncSession, tenant_id: uuid.UUID):
    franchisee = Franchisee(tenant_id=tenant_id, name="Вася")
    db.add(franchisee)
    await db.flush()
    his_store = Store(tenant_id=tenant_id, name="П14", franchisee_id=franchisee.id)
    own_store = Store(tenant_id=tenant_id, name="Л15")
    archived_store = Store(tenant_id=tenant_id, name="Старый", franchisee_id=franchisee.id)
    db.add_all([his_store, own_store, archived_store])
    await db.flush()
    archived_store.archived_at = datetime.now(UTC)
    await db.flush()

    principal, _ = await _profile_for(
        db,
        tenant_id,
        email="owner@t.ru",
        org_role="franchisee_owner",
        franchisee_id=franchisee.id,
    )
    scope = await resolve_scope(db, principal)
    assert scope.kind == "stores"
    assert scope.store_ids == frozenset({his_store.id})


async def test_archived_profile_scope_is_self(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _profile_for(db, tenant_id, email="fired@t.ru", org_role="tu")
    await archive_profile(db, profile, reason="manual", actor_id=None)
    scope = await resolve_scope(db, principal)
    assert scope.kind == "self"
