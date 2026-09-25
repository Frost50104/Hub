"""Отделы: смена родителя сразу меняет членство аудиторий.

Правило «отделу X» матчит и под-отделы. До фикса ручка пересчитывала без
flush: сессия autoflush=False, загрузчик карт читал старого родителя, и
сотрудник под-отдела не попадал в аудиторию нового родителя до следующего
полного пересчёта.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.org import update_department
from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Department
from app.schemas.org import DepartmentUpdate
from app.services.audience_resolver import recalc_audience
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.services import notify_batch

    monkeypatch.setattr(notify_batch, "schedule_push_batch", lambda batch: None)


async def _members(db: AsyncSession, audience_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(AudienceMember.profile_id).where(AudienceMember.audience_id == audience_id)
    )
    return {r[0] for r in rows}


async def test_reparent_moves_subtree_into_parent_audience(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = make_principal(
        tenant_id, email="dep-admin@t.ru", role="admin", tenant_slug=f"dep-{tenant_id.hex[:8]}"
    )
    await _register(db, admin)
    office = Department(tenant_id=tenant_id, name="Офис")
    purchasing = Department(tenant_id=tenant_id, name="Закупки")
    db.add_all([office, purchasing])
    await db.flush()
    buyer = EmployeeProfile(
        tenant_id=tenant_id,
        email="buyer@t.ru",
        full_name="Закупщик",
        department_id=purchasing.id,
    )
    audience = Audience(tenant_id=tenant_id)
    db.add_all([buyer, audience])
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            department_ids=[office.id],
        )
    )
    await db.flush()
    await recalc_audience(db, audience)
    assert buyer.id not in await _members(db, audience.id)

    await update_department(purchasing.id, DepartmentUpdate(parent_id=office.id), admin, db)

    assert buyer.id in await _members(db, audience.id)
