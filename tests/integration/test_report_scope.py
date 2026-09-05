"""Скоуп отчётов iiko по франчайзи (выкат 3б, HUB_TASK_sites_mirror).

Владелец франчайзи видит только свои точки: свои магазины → stores.site_id →
shadow_sites.refs (system=iiko) → Department.Id. Publisher/admin/офис/ТУ —
полная сеть, как раньше (основание допуска решает).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.reports import _franchisee_department_ids, _require_report_access
from app.models.employee_profile import EmployeeProfile
from app.models.org import Franchisee, Store
from app.models.shadow import ShadowSite, ShadowUser
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _seed_franchisee_owner(db: AsyncSession, tenant_id: uuid.UUID):
    principal = make_principal(tenant_id=tenant_id, role="member", email="fr@t.ru")
    db.add(
        ShadowUser(
            employee_id=principal.employee_id,
            tenant_id=tenant_id,
            email="fr@t.ru",
            full_name="Владелец Франчайзи",
        )
    )
    fr = Franchisee(tenant_id=tenant_id, name="ИП Тестова")
    db.add(fr)
    await db.flush()
    db.add(
        EmployeeProfile(
            tenant_id=tenant_id,
            employee_id=principal.employee_id,
            email="fr@t.ru",
            full_name="Владелец Франчайзи",
            org_role="franchisee_owner",
            franchisee_id=fr.id,
        )
    )
    await db.flush()
    return principal, fr


async def test_franchisee_department_ids_via_registry(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Свои магазины → site → iiko-ref; дубли магазинов на один объект дают
    ОДИН Department.Id; чужой магазин и магазин без site_id не участвуют."""
    principal, fr = await _seed_franchisee_owner(db, tenant_id)
    site_a, site_b = uuid.uuid4(), uuid.uuid4()
    for site_id, dep in ((site_a, "dep-a"), (site_b, "dep-b")):
        db.add(
            ShadowSite(
                site_id=site_id,
                tenant_id=tenant_id,
                name="Точка",
                refs=[{"system": "iiko", "external_id": dep},
                      {"system": "hub", "external_id": str(uuid.uuid4())}],
                synced_at=datetime.now(UTC),
            )
        )
    db.add_all(
        [
            Store(tenant_id=tenant_id, name="Своя А", franchisee_id=fr.id, site_id=site_a),
            # Дубль на тот же объект — Department.Id не задваивается.
            Store(tenant_id=tenant_id, name="Своя А (дубль)", franchisee_id=fr.id, site_id=site_a),
            Store(tenant_id=tenant_id, name="Своя Б", franchisee_id=fr.id, site_id=site_b),
            Store(tenant_id=tenant_id, name="Своя без связи", franchisee_id=fr.id),
            Store(tenant_id=tenant_id, name="Чужая", site_id=site_b),
        ]
    )
    await db.flush()

    assert await _franchisee_department_ids(db, principal) == ["dep-a", "dep-b"]


async def test_basis_full_vs_franchisee(db: AsyncSession, tenant_id: uuid.UUID):
    """hub-admin допущен как full даже с профилем франчайзи; владелец без
    иных оснований — franchisee; ноль привязок → пустой список (в _build это
    явный отказ, не пустой фильтр)."""
    principal, _fr = await _seed_franchisee_owner(db, tenant_id)
    assert await _require_report_access(db, principal) == "franchisee"
    assert await _franchisee_department_ids(db, principal) == []  # магазинов нет

    admin = make_principal(tenant_id=tenant_id, role="admin", email="adm@t.ru")
    assert await _require_report_access(db, admin) == "full"
