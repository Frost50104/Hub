"""Выгрузка кадровых данных для auth — от БД до файла, под настоящим RLS.

Роль без суперпользователя (`rls_enforced`): файл одного тенанта не видит
чужой. Снимок — REPEATABLE READ READ ONLY опцией соединения (asyncpg обязан её
принять). Файл — 0600; архивная карточка человека без учётки не выгружается, её
строка ТУ выпадает, ссылка на неё как на руководителя становится null.
"""

from __future__ import annotations

import json
import stat
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.jobs import export_hr_for_auth
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Department, Franchisee, Position
from tests.integration._race_seed import seed_network
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


async def _card(db: AsyncSession, employee_id: uuid.UUID) -> EmployeeProfile:
    return (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.employee_id == employee_id))
    ).scalar_one()


async def test_export_reads_own_tenant_only_and_writes_private_file(
    db: AsyncSession, tenant_id, tmp_path
):
    net = await seed_network(db, tenant_id, enable=False)
    position = Position(tenant_id=tenant_id, name="Бариста", position=3)
    parent = Department(tenant_id=tenant_id, name="Офис")
    franchisee = Franchisee(tenant_id=tenant_id, name="ИП Тест")
    db.add_all([position, parent, franchisee])
    await db.flush()
    child = Department(tenant_id=tenant_id, name="Закупки", parent_id=parent.id)
    gone = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=None,
        email=f"gone-{net.slug}@t.ru",
        full_name="Уволен",
        org_role="employee",
        status="archived",
        archived_at=datetime.now(UTC),
        archive_reason="manual",
        account_kind="person",
        store_id=net.D.id,
    )
    db.add_all([child, gone])
    await db.flush()
    net.C.franchisee_id = franchisee.id
    emp_a = await _card(db, net.emp_a.employee_id)
    emp_a.position_id = position.id
    emp_a.hired_at = date(2024, 3, 1)
    emp_a.manager_profile_id = gone.id
    emp_c = await _card(db, net.emp_c.employee_id)
    emp_c.org_role = "tu"
    office = await _card(db, net.office.employee_id)
    office.department_id = child.id
    db.add_all(
        [
            TuStoreAssignment(tenant_id=tenant_id, profile_id=emp_c.id, store_id=net.C.id),
            TuStoreAssignment(tenant_id=tenant_id, profile_id=gone.id, store_id=net.A.id),
        ]
    )
    await db.commit()

    # Чужой тенант с карточкой — в наш файл попасть не должен.
    other = uuid.uuid4()
    async with tenant_scoped_session(other) as sb:
        stranger = make_principal(
            other, email=f"s-{uuid.uuid4().hex[:8]}@t.ru", tenant_slug=f"o-{uuid.uuid4().hex[:8]}"
        )
        await _register(sb, stranger)
        sb.add(
            EmployeeProfile(
                tenant_id=other,
                employee_id=stranger.employee_id,
                email=stranger.email,
                full_name="Чужой",
                org_role="employee",
                status="active",
                account_kind="person",
            )
        )
        await sb.commit()

    out = tmp_path / "hr.json"
    assert await export_hr_for_auth.run(net.slug, out) == 0

    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["tenant_id"] == str(tenant_id)
    assert doc["counts"] == {k: len(doc[k]) for k in export_hr_for_auth.COLLECTIONS}
    assert export_hr_for_auth.structural_problems(doc) == []
    profiles = {p["id"]: p for p in doc["profiles"]}
    # Сид: четыре человека и касса — все активны; архивная без учётки выпала.
    assert len(profiles) == 5
    assert str(gone.id) not in profiles
    assert all(p["full_name"] != "Чужой" for p in profiles.values())
    a = profiles[str(emp_a.id)]
    assert a["manager_profile_id"] is None
    assert a["hired_at"] == "2024-03-01"
    assert a["position_id"] == str(position.id)
    assert doc["tu_assignments"] == [{"profile_id": str(emp_c.id), "store_id": str(net.C.id)}]
    assert {d["id"]: d["parent_id"] for d in doc["departments"]}[str(child.id)] == str(parent.id)
    assert {s["id"]: s["franchisee_id"] for s in doc["stores"]}[str(net.C.id)] == str(franchisee.id)
    assert [p["sort_order"] for p in doc["positions"]] == [3]


async def test_unknown_tenant_writes_nothing(tmp_path):
    out = tmp_path / "hr.json"
    assert await export_hr_for_auth.run(f"no-such-{uuid.uuid4().hex[:8]}", out) == 2
    assert not out.exists()
