"""Заморозка кадровых данных в Hub (16d, 0063): гейты ручек и окно каткатa.

Правило одно: пока организация `authoritative` (или открыто окно каткатa),
кадровые поля карточки ЧЕЛОВЕКА и справочники ведёт auth. Отказ — только на
изменённое значение: формы шлют объект целиком, вчерашние бандлы тоже, и
сохранение телефона или прав обязано проходить. Кассы (требование 7) —
поля Hub, как раньше.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api import employees as employees_api
from app.api import org as org_api
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.hr_sync import HrSyncState
from app.models.org import Department, Franchisee, Position, Store
from app.models.shadow import ShadowUser
from app.schemas.employee import EmployeeUpdate, RestoreBody, TuStoresReplace
from app.schemas.org import DepartmentUpdate, RefCreate, StoreCreate, StoreUpdate
from app.services import hr_state, notify_batch
from app.services.registry_apply import apply_registry
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    async def _noop(**kw) -> None:
        return None

    monkeypatch.setattr(employees_api, "enforce_rate_limit", _noop)
    monkeypatch.setattr(notify_batch, "schedule_push_batch", lambda batch: None)


async def _admin(db: AsyncSession, tenant_id: uuid.UUID):
    admin = make_principal(
        tenant_id,
        email=f"adm-{tenant_id.hex[:8]}@t.ru",
        role="admin",
        tenant_slug=f"frz-{tenant_id.hex[:10]}",
    )
    await _register(db, admin)
    return admin


async def _freeze(db: AsyncSession, tenant_id: uuid.UUID, *, window: bool = False) -> None:
    db.add(
        HrSyncState(
            tenant_id=tenant_id,
            in_snapshot=True,
            authoritative=not window,
            cutover_freeze=window,
            last_applied_at=datetime.now(UTC),
        )
    )
    await db.flush()


async def _card(db: AsyncSession, tenant_id: uuid.UUID, **fields) -> EmployeeProfile:
    email = f"{uuid.uuid4().hex[:8]}@t.ru"
    card = EmployeeProfile(tenant_id=tenant_id, email=email, full_name="Сотрудник", **fields)
    db.add(card)
    await db.flush()
    return card


async def _refused(coro, code: int, text: str | None = None) -> None:
    with pytest.raises(HTTPException) as err:
        await coro
    assert err.value.status_code == code
    if text is not None:
        assert err.value.detail == text


# --- Карточка ----------------------------------------------------------------------------


async def test_patch_refuses_only_changed_hr_value_of_person(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin(db, tenant_id)
    old = Position(tenant_id=tenant_id, name="Бариста")
    new = Position(tenant_id=tenant_id, name="Повар")
    db.add_all([old, new])
    await db.flush()
    person = await _card(db, tenant_id, position_id=old.id)
    cashier = await _card(db, tenant_id, account_kind="service", position_id=old.id)
    await _freeze(db, tenant_id)

    await _refused(
        employees_api.update_employee(person.id, EmployeeUpdate(position_id=new.id), admin, db),
        422,
        hr_state.HR_FROZEN_DETAIL,
    )
    # Форма шлёт объект целиком: неизменённое кадровое поле + новый телефон — 200.
    resp = await employees_api.update_employee(
        person.id, EmployeeUpdate(position_id=old.id, phone="+7 900"), admin, db
    )
    assert resp.phone == "+7 900" and resp.hr_locked is True
    # Касса — поля Hub (требование 7).
    resp = await employees_api.update_employee(
        cashier.id, EmployeeUpdate(position_id=new.id), admin, db
    )
    assert resp.position_id == new.id and resp.hr_locked is False


async def test_tu_same_set_passes_changed_set_refused(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id)
    s1, s2 = Store(tenant_id=tenant_id, name="Т1"), Store(tenant_id=tenant_id, name="Т2")
    db.add_all([s1, s2])
    await db.flush()
    tu = await _card(db, tenant_id, org_role="tu")
    db.add(TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=s1.id))
    await _freeze(db, tenant_id)

    resp = await employees_api.replace_tu_stores(
        tu.id, TuStoresReplace(store_ids=[s1.id]), admin, db
    )
    assert resp.tu_store_ids == [s1.id]
    await _refused(
        employees_api.replace_tu_stores(
            tu.id, TuStoresReplace(store_ids=[s1.id, s2.id]), admin, db
        ),
        422,
        hr_state.HR_TU_DETAIL,
    )


async def test_restore_of_deactivated_card_waits_for_auth(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id)
    employee_id = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=employee_id,
            tenant_id=tenant_id,
            email="off@t.ru",
            full_name="Отключён",
            auth_active=False,
        )
    )
    await db.flush()
    card = await _card(
        db,
        tenant_id,
        employee_id=employee_id,
        status="archived",
        archive_reason="auth_deactivated",
        archived_at=datetime.now(UTC),
    )
    await _freeze(db, tenant_id)
    await _refused(
        employees_api.restore_employee(card.id, RestoreBody(), admin, db),
        409,
        hr_state.HR_RESTORE_DEACTIVATED_DETAIL,
    )
    shadow = await db.get(ShadowUser, employee_id)
    shadow.auth_active = True
    await db.flush()
    resp = await employees_api.restore_employee(card.id, RestoreBody(), admin, db)
    assert resp.status == "active"


# --- Справочники и точки ----------------------------------------------------------------


async def test_directories_are_read_only_when_frozen(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id)
    dep = Department(tenant_id=tenant_id, name="Офис")
    db.add(dep)
    await db.flush()
    await _freeze(db, tenant_id)
    await _refused(
        org_api.create_position(RefCreate(name="Новая"), admin, db),
        409,
        hr_state.HR_DIRECTORY_DETAIL,
    )
    await _refused(
        org_api.create_franchisee(RefCreate(name="ИП"), admin, db),
        409,
        hr_state.HR_DIRECTORY_DETAIL,
    )
    await _refused(
        org_api.update_department(dep.id, DepartmentUpdate(name="Другой"), admin, db),
        409,
        hr_state.HR_DIRECTORY_DETAIL,
    )


async def test_store_franchisee_frozen_other_fields_editable(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin(db, tenant_id)
    fr = Franchisee(tenant_id=tenant_id, name="ИП Петров")
    db.add(fr)
    await db.flush()
    store = Store(tenant_id=tenant_id, name="Точка", franchisee_id=fr.id)
    db.add(store)
    await db.flush()
    await _freeze(db, tenant_id)
    await _refused(
        org_api.create_store(StoreCreate(name="Новая", franchisee_id=fr.id), admin, db),
        422,
        hr_state.HR_STORE_FRANCHISEE_DETAIL,
    )
    await _refused(
        org_api.update_store(store.id, StoreUpdate(franchisee_id=None), admin, db),
        422,
        hr_state.HR_STORE_FRANCHISEE_DETAIL,
    )
    resp = await org_api.update_store(
        store.id, StoreUpdate(name="Точка 2", franchisee_id=fr.id), admin, db
    )
    assert resp.name == "Точка 2" and resp.franchisee_id == fr.id


async def test_store_with_tu_rows_is_busy_when_frozen(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id)
    store = Store(tenant_id=tenant_id, name="Точка ТУ")
    db.add(store)
    await db.flush()
    tu = await _card(db, tenant_id, org_role="tu")
    db.add(TuStoreAssignment(tenant_id=tenant_id, profile_id=tu.id, store_id=store.id))
    await _freeze(db, tenant_id)
    await _refused(org_api.delete_store(store.id, admin, db), 409)


async def test_org_snapshot_reports_freeze(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id)
    snap = await org_api.org_snapshot(admin, db)
    assert snap.hr is None
    await _freeze(db, tenant_id)
    snap = await org_api.org_snapshot(admin, db)
    assert snap.hr is not None and snap.hr.frozen and snap.hr.state == "paused"
    assert snap.hr.edit_url.endswith("/admin/employees")


# --- Окно каткатa -----------------------------------------------------------------------


async def test_window_closes_links_archive_restore_sites_and_registry(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin(db, tenant_id)
    store = Store(tenant_id=tenant_id, name="Точка", site_id=uuid.uuid4())
    db.add(store)
    card = await _card(db, tenant_id)
    await _freeze(db, tenant_id, window=True)
    from app.schemas.employee import ArchiveBody, LinkBody

    await _refused(
        employees_api.archive_employee(card.id, ArchiveBody(reason="manual"), admin, db),
        409,
        hr_state.HR_WINDOW_DETAIL,
    )
    await _refused(
        employees_api.link_employee_login(card.id, LinkBody(employee_id=uuid.uuid4()), admin, db),
        409,
        hr_state.HR_WINDOW_DETAIL,
    )
    await _refused(
        org_api.update_store(store.id, StoreUpdate(site_id=None), admin, db),
        409,
        hr_state.HR_WINDOW_DETAIL,
    )
    await _refused(
        org_api.create_position(RefCreate(name="Любая"), admin, db),
        409,
        hr_state.HR_WINDOW_DETAIL,
    )
    report = await apply_registry(db, tenant_id)
    assert report.skipped_window is True


# --- CSV ----------------------------------------------------------------------------------


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="import.csv")


async def test_csv_rows_changing_person_hr_are_errors_phones_pass(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin(db, tenant_id)
    barista = Position(tenant_id=tenant_id, name="Бариста")
    db.add(barista)
    await db.flush()
    same = await _card(db, tenant_id, position_id=barista.id)
    changing = await _card(db, tenant_id)
    cashier = await _card(db, tenant_id, account_kind="service")
    await _freeze(db, tenant_id)
    csv_text = (
        "email;phone;position\n"
        f"{same.email};+7 111;Бариста\n"
        f"{changing.email};+7 222;Бариста\n"
        f"{cashier.email};+7 333;Бариста\n"
        f"{same.email};+7 444;Кондитер\n"
    )
    report = await employees_api.import_employees(
        file=_upload(csv_text),
        dry_run=False,
        create_missing_refs=False,
        suppress_automations=True,
        principal=admin,
        db=db,
    )
    assert report.updated == 2  # телефон неизменённой карточки + касса целиком
    assert any("Строка 3:" in e and "ведутся в auth" in e for e in report.errors)
    assert any("Строка 5:" in e and "справочники ведутся в auth" in e for e in report.errors)
    created = await db.execute(select(Position).where(Position.name == "Кондитер"))
    assert created.scalar_one_or_none() is None
    await db.refresh(changing)
    assert changing.position_id is None and changing.phone is None
    await db.refresh(cashier)
    assert cashier.position_id == barista.id
