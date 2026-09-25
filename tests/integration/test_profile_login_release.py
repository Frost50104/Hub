"""Архивная карточка отдаёт вход при удалении учётки; восстановление с нуля.

- `archive_profile` на архивной карточке был безусловным no-op: карточка,
  заархивированная правилом неактивности (вход она держит), при удалении или
  переводе учётки в auth оставляла `employee_id` занятым навсегда — а он
  уникален глобально, и в новой организации человеку карточку не завести.
- `restore_profile` не сбрасывал предупреждение о неактивности: джоба
  архивировала вернувшегося уже наутро.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from signaris_auth.sync import DeletionEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile
from app.models.shadow import ShadowUser
from app.services import staff_sync
from app.services.deletion_sync import _on_event
from app.services.employee_profiles import archive_profile, restore_profile

pytestmark = pytest.mark.integration


async def _bound_card(
    db: AsyncSession, tenant_id: uuid.UUID, *, email: str, reason: str | None = None
) -> EmployeeProfile:
    employee_id = uuid.uuid4()
    db.add(ShadowUser(employee_id=employee_id, tenant_id=tenant_id, email=email, full_name=email))
    await db.flush()
    now = dt.datetime.now(dt.UTC)
    card = EmployeeProfile(
        tenant_id=tenant_id,
        email=email,
        full_name=email,
        employee_id=employee_id,
        status="archived" if reason else "active",
        archive_reason=reason,
        archived_at=now if reason else None,
        last_activity_at=now - dt.timedelta(days=200),
        inactivity_warned_at=now - dt.timedelta(days=100),
    )
    db.add(card)
    await db.flush()
    return card


async def test_deletion_releases_login_of_inactivity_archived_card(
    db: AsyncSession, tenant_id: uuid.UUID
):
    card = await _bound_card(db, tenant_id, email="idle@t.ru", reason="auto_inactivity")
    employee_id = card.employee_id
    await db.commit()

    await _on_event(
        db,
        DeletionEvent(
            seq=1,
            event_type="employee_deleted",
            employee_id=employee_id,
            tenant_id=tenant_id,
            created_at=dt.datetime.now(dt.UTC),
        ),
    )

    await db.refresh(card)
    assert card.status == "archived"
    assert card.employee_id is None
    assert card.archive_reason == "auth_deleted"
    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.object_id == card.id, AuditLog.action == "archive")
        )
    ).scalar_one()
    assert audit.diff == {"reason": {"old": "auto_inactivity", "new": "auth_deleted"}}


async def test_already_unbound_archive_stays_noop(db: AsyncSession, tenant_id: uuid.UUID):
    """Ручной архив вход уже отдал — повторная архивация ничего не пишет."""
    card = await _bound_card(db, tenant_id, email="gone@t.ru", reason="manual")
    card.employee_id = None
    await db.flush()
    await archive_profile(db, card, reason="auth_deleted", actor_id=None)
    assert card.archive_reason == "manual"


async def test_staff_row_deleted_releases_archived_card(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Та же отвязка из ветки удалённых строк синка (толерантность к контракту)."""
    card = await _bound_card(db, tenant_id, email="idle2@t.ru", reason="auto_inactivity")
    row = {
        "kind": "employee",
        "employee_id": str(card.employee_id),
        "tenant_id": str(tenant_id),
        "email": "idle2@t.ru",
        "full_name": "idle2@t.ru",
        "role": "member",
        "is_active": False,
        "deleted_at": "2026-09-25T10:00:00Z",
    }
    await db.commit()

    async def fake_fetch():  # noqa: ANN202
        return [row]

    monkeypatch.setattr(staff_sync, "_fetch_staff_pages", fake_fetch)
    report = await staff_sync.sync_staff()
    assert report.failed_tenants == 0
    assert report.archived == 0  # карточка уже была в архиве

    await db.refresh(card)
    assert card.employee_id is None and card.archive_reason == "auth_deleted"


async def test_restore_resets_inactivity_warning(db: AsyncSession, tenant_id: uuid.UUID):
    card = await _bound_card(db, tenant_id, email="back@t.ru", reason="auto_inactivity")
    assert card.inactivity_warned_at is not None
    await restore_profile(db, card, actor_id=None)
    assert card.status == "active"
    assert card.inactivity_warned_at is None
