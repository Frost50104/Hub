"""Общий сид сети для тестов «Гусиной гонки»: четыре точки, два подразделения
iiko (A и B — дубли одного), две группы точек, пять карточек."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.models.org import Store, StoreGroup, StoreGroupMember
from app.models.shadow import ShadowSite
from app.services.race import gate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register


async def seed_network(db: AsyncSession, tenant_id: uuid.UUID, *, enable: bool = True):
    slug = f"race-{uuid.uuid4().hex[:8]}"
    admin = make_principal(tenant_id, email=f"admin-{slug}@t.ru", role="admin", tenant_slug=slug)
    await _register(db, admin)

    site_a, site_c = uuid.uuid4(), uuid.uuid4()
    stores = {
        "A": Store(tenant_id=tenant_id, name="Арсенальная", code="А1", site_id=site_a),
        "B": Store(tenant_id=tenant_id, name="Арсенальная дубль", code="А1д", site_id=site_a),
        "C": Store(tenant_id=tenant_id, name="Ветеранов", code="В2", site_id=site_c),
        "D": Store(tenant_id=tenant_id, name="Дальняя без реестра", code="Д3"),
    }
    db.add_all(stores.values())
    await db.flush()
    now = datetime.now(UTC)
    db.add_all(
        [
            ShadowSite(
                site_id=site_a,
                tenant_id=tenant_id,
                name="Арсенальная",
                refs=[
                    {"system": "iiko", "external_id": "dep-1"},
                    {"system": "hub", "external_id": str(stores["A"].id)},
                    {"system": "hub", "external_id": str(stores["B"].id)},
                ],
                synced_at=now,
            ),
            ShadowSite(
                site_id=site_c,
                tenant_id=tenant_id,
                name="Ветеранов",
                refs=[{"system": "iiko", "external_id": "dep-2"}],
                synced_at=now,
            ),
        ]
    )
    g1 = StoreGroup(tenant_id=tenant_id, name="Центр")
    g2 = StoreGroup(tenant_id=tenant_id, name="Область")
    db.add_all([g1, g2])
    await db.flush()
    db.add_all(
        [
            StoreGroupMember(tenant_id=tenant_id, group_id=g1.id, store_id=stores["A"].id),
            StoreGroupMember(tenant_id=tenant_id, group_id=g2.id, store_id=stores["C"].id),
            StoreGroupMember(tenant_id=tenant_id, group_id=g2.id, store_id=stores["B"].id),
        ]
    )

    people = {}
    for key, store, kind in (
        ("emp_a", "A", "person"),
        ("emp_b", "B", "person"),
        ("emp_c", "C", "person"),
        ("cashier_a", "A", "service"),
        ("office", None, "person"),
    ):
        p = make_principal(tenant_id, email=f"{key}-{slug}@t.ru", role="member", tenant_slug=slug)
        await _register(db, p)
        db.add(
            EmployeeProfile(
                tenant_id=tenant_id,
                employee_id=p.employee_id,
                email=p.email,
                full_name=key,
                org_role="office" if store is None else "employee",
                status="active",
                account_kind=kind,
                store_id=stores[store].id if store else None,
            )
        )
        people[key] = p
    await db.flush()
    if enable:
        await gate.set_tenant_enabled(db, tenant_id, True)
    return SimpleNamespace(
        admin=admin,
        slug=slug,
        A=stores["A"],
        B=stores["B"],
        C=stores["C"],
        D=stores["D"],
        g1=g1,
        g2=g2,
        **people,
    )
