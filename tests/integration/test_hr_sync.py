"""Кадровые данные из auth (16d, 0063): синк штата + снимок справочников → карточки.

Под настоящим RLS (`rls_enforced`), как на проде. Фетчеры штата и справочников
подменяются monkeypatch'ем. Проверяем то, на чём держится безопасность:
- отчёт ничего не пишет, а заморозка всё равно ставится;
- применение — справочники до карточек, новые карточки сразу с полями,
  руководитель-новичок того же прогона, ТУ, франчайзи точки по объекту;
- повторный прогон — ноль изменений (приёмка каткатa);
- предохранитель держит изменения заполненных карточек, но не новых людей;
  обход применяет ровно показанный набор;
- правило K: архив → возврат при том же имени → отвязка при другом;
- сбой снимка не снимает заморозку; старый снимок после нового не применяется.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.hr_sync import HrSyncState
from app.models.org import Department, Franchisee, Position, Store
from app.models.shadow import ShadowUser
from app.services import hr_sync, notify_batch, staff_sync
from app.services.org_directory_sync import parse_directory
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — RLS реально действует, как на проде
    yield


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    sent: list = []
    monkeypatch.setattr(notify_batch, "schedule_push_batch", sent.append)
    return sent


@pytest.fixture
def hr_env(monkeypatch):
    from app.config import get_settings

    def configure(**values: object) -> None:
        for key, value in values.items():
            monkeypatch.setenv(f"SIGNARIS_HUB_{key.upper()}", str(value))
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def _mail(tenant_id: uuid.UUID, local: str) -> str:
    """Почта, уникальная для теста: синк коммитит, а тесты под суперпользователем
    видят все организации — одинаковый адрес ловил бы чужую карточку."""
    return f"{local}-{tenant_id.hex[:8]}@t.ru"


def _slug(tenant_id: uuid.UUID) -> str:
    return f"hr-{tenant_id.hex[:10]}"


def _hr(**kw: object) -> dict:
    block: dict = {
        "authoritative": True,
        "hired_at": None,
        "org_role": "employee",
        "position_id": None,
        "department_id": None,
        "franchisee_id": None,
        "site_id": None,
        "manager_employee_id": None,
        "assigned_site_ids": [],
    }
    for key, value in kw.items():
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, list):
            value = [str(v) for v in value]
        block[key] = value
    return block


def _row(tenant_id: uuid.UUID, employee_id: uuid.UUID, email: str, name: str, **kw) -> dict:
    row = {
        "kind": "employee",
        "employee_id": str(employee_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "full_name": name,
        "role": kw.pop("role", "member"),
        "account_kind": kw.pop("account_kind", "person"),
        "is_active": kw.pop("is_active", True),
        "deleted_at": None,
    }
    if "hr" in kw:
        row["hr"] = kw.pop("hr")
    return row


def _directory(tenant_id: uuid.UUID, *, authoritative: bool = True, **colls) -> object:
    body = {
        "tenants": [{"tenant_id": str(tenant_id), "authoritative": authoritative}],
        "positions": colls.get("positions", []),
        "departments": colls.get("departments", []),
        "franchisees": colls.get("franchisees", []),
        "site_franchisees": colls.get("site_franchisees", []),
    }
    for name in ("positions", "departments", "franchisees", "site_franchisees"):
        for item in body[name]:
            item.setdefault("tenant_id", str(tenant_id))
    body["totals"] = {
        n: len(body[n]) for n in ("positions", "departments", "franchisees", "site_franchisees")
    }
    return parse_directory(body)


def _mock(monkeypatch, *, directory, rows) -> None:
    async def fake_directory(**kw):  # noqa: ANN003, ANN202
        return directory

    async def fake_staff(**kw):  # noqa: ANN003, ANN202
        return rows

    monkeypatch.setattr(staff_sync, "fetch_org_directory", fake_directory)
    monkeypatch.setattr(staff_sync, "_fetch_staff_pages", fake_staff)


async def _person(
    db: AsyncSession, tenant_id: uuid.UUID, email: str, name: str, **fields
) -> EmployeeProfile:
    employee_id = uuid.uuid4()
    db.add(ShadowUser(employee_id=employee_id, tenant_id=tenant_id, email=email, full_name=name))
    await db.flush()
    card = EmployeeProfile(
        tenant_id=tenant_id, email=email, full_name=name, employee_id=employee_id, **fields
    )
    db.add(card)
    await db.flush()
    return card


async def _state(tenant_id: uuid.UUID) -> HrSyncState:
    async with tenant_scoped_session(tenant_id) as s:
        return (await s.execute(select(HrSyncState))).scalar_one()


class _Seed:
    pass


async def _seed(db: AsyncSession, tenant_id: uuid.UUID) -> _Seed:
    seed = _Seed()
    admin = make_principal(
        tenant_id, email=f"adm-{tenant_id.hex[:6]}@t.ru", role="admin", tenant_slug=_slug(tenant_id)
    )
    await _register(db, admin)
    seed.p_barista = Position(tenant_id=tenant_id, name="Бариста", position=1)
    seed.d_office = Department(tenant_id=tenant_id, name="Офис")
    seed.f_ip = Franchisee(tenant_id=tenant_id, name="ИП Иванов")
    db.add_all([seed.p_barista, seed.d_office, seed.f_ip])
    await db.flush()
    seed.site_1, seed.site_2 = uuid.uuid4(), uuid.uuid4()
    seed.s1 = Store(tenant_id=tenant_id, name="Точка 1", site_id=seed.site_1)
    seed.s2 = Store(tenant_id=tenant_id, name="Точка 2", site_id=seed.site_2)
    db.add_all([seed.s1, seed.s2])
    await db.flush()
    seed.filled = await _person(
        db,
        tenant_id,
        _mail(tenant_id, "filled"),
        "Заполненная Карточка",
        position_id=seed.p_barista.id,
        store_id=seed.s1.id,
    )
    seed.empty = await _person(db, tenant_id, _mail(tenant_id, "empty"), "Пустая Карточка")
    await db.commit()
    return seed


def _dir_rows(seed: _Seed, *, new_position: uuid.UUID, office_name: str = "Офис") -> dict:
    return {
        "positions": [
            {"id": str(seed.p_barista.id), "name": "Бариста", "sort_order": 1, "archived_at": None},
            {"id": str(new_position), "name": "Пекарь", "sort_order": 2, "archived_at": None},
        ],
        "departments": [
            {
                "id": str(seed.d_office.id),
                "name": office_name,
                "parent_id": None,
                "archived_at": None,
            }
        ],
        "franchisees": [
            {
                "id": str(seed.f_ip.id),
                "name": "ИП Иванов",
                "contact_info": None,
                "archived_at": None,
            }
        ],
        "site_franchisees": [{"site_id": str(seed.site_1), "franchisee_id": str(seed.f_ip.id)}],
    }


async def _card(db: AsyncSession, card_id: uuid.UUID) -> EmployeeProfile:
    return await _fresh(db, select(EmployeeProfile).where(EmployeeProfile.id == card_id))


async def _fresh(db: AsyncSession, stmt):  # noqa: ANN001, ANN202
    """Строка, которую записал синк (своими сессиями), — поверх кеша сессии."""
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one()


# --- Отчёт и применение ------------------------------------------------------------


async def test_report_mode_freezes_but_writes_nothing(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants="")  # тенант не в списке
    baker = uuid.uuid4()
    rows = [
        _row(
            tenant_id,
            seed.filled.employee_id,
            _mail(tenant_id, "filled"),
            "Заполненная Карточка",
            hr=_hr(position_id=baker, site_id=seed.site_2),
        )
    ]
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=baker))
    _mock(monkeypatch, directory=directory, rows=rows)

    report = await staff_sync.sync_staff()

    hr_report = report.hr[str(tenant_id)]
    assert hr_report["mode"] == "report"
    assert hr_report["cards"]["change"] == [str(seed.filled.id)]
    assert hr_report["directory"]["ops"] == {"position_create": 1, "store_franchisee": 1}
    card = await _card(db, seed.filled.id)
    assert card.position_id == seed.p_barista.id and card.store_id == seed.s1.id
    created = await db.execute(select(Position).where(Position.id == baker))
    assert created.scalar_one_or_none() is None
    state = await _state(tenant_id)
    # Заморозка — по снимку, а не по списку применения.
    assert state.authoritative is True and state.last_mode == "report"


async def test_apply_writes_directory_cards_new_people_and_is_idempotent(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env, _no_push
):
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants=_slug(tenant_id))
    baker = uuid.uuid4()
    lead_eid, junior_eid = uuid.uuid4(), uuid.uuid4()
    tu_card = await _person(
        db, tenant_id, _mail(tenant_id, "tu"), "Территориальный Управляющий", org_role="tu"
    )
    await db.commit()
    rows = [
        _row(
            tenant_id,
            seed.filled.employee_id,
            _mail(tenant_id, "filled"),
            "Заполненная Карточка",
            hr=_hr(position_id=baker, site_id=seed.site_2, department_id=seed.d_office.id),
        ),
        _row(
            tenant_id,
            seed.empty.employee_id,
            _mail(tenant_id, "empty"),
            "Пустая Карточка",
            hr=_hr(position_id=seed.p_barista.id, site_id=seed.site_1, hired_at="2025-02-03"),
        ),
        _row(
            tenant_id,
            tu_card.employee_id,
            _mail(tenant_id, "tu"),
            "Территориальный Управляющий",
            hr=_hr(org_role="tu", assigned_site_ids=[seed.site_1, seed.site_2]),
        ),
        # Двое новых: руководитель и подчинённый — в одном прогоне.
        _row(
            tenant_id,
            junior_eid,
            _mail(tenant_id, "junior"),
            "Новый Сотрудник",
            hr=_hr(position_id=baker, site_id=seed.site_1, manager_employee_id=lead_eid),
        ),
        _row(
            tenant_id,
            lead_eid,
            _mail(tenant_id, "lead"),
            "Новый Руководитель",
            hr=_hr(org_role="office", department_id=seed.d_office.id),
        ),
    ]
    directory = _directory(
        tenant_id, **_dir_rows(seed, new_position=baker, office_name="Главный офис")
    )
    _mock(monkeypatch, directory=directory, rows=rows)

    report = await staff_sync.sync_staff()
    hr_report = report.hr[str(tenant_id)]
    assert hr_report["mode"] == "apply", hr_report
    assert report.profiles_created == 0  # новых людей заводит кадровая часть
    assert len(hr_report["applied"]["created"]) == 2
    assert hr_report["cards"]["fill"] == [str(seed.empty.id)]

    filled = await _card(db, seed.filled.id)
    assert (filled.position_id, filled.store_id, filled.department_id) == (
        baker,
        seed.s2.id,
        seed.d_office.id,
    )
    empty = await _card(db, seed.empty.id)
    assert empty.hired_at == date(2025, 2, 3) and empty.store_id == seed.s1.id
    tu_stores = set(
        (
            await db.execute(
                select(TuStoreAssignment.store_id).where(TuStoreAssignment.profile_id == tu_card.id)
            )
        ).scalars()
    )
    assert tu_stores == {seed.s1.id, seed.s2.id}
    junior = await _fresh(
        db, select(EmployeeProfile).where(EmployeeProfile.employee_id == junior_eid)
    )
    lead = await _fresh(db, select(EmployeeProfile).where(EmployeeProfile.employee_id == lead_eid))
    assert junior.position_id == baker and junior.manager_profile_id == lead.id
    assert lead.org_role == "office" and junior.last_activity_at is None
    office = await _fresh(db, select(Department).where(Department.id == seed.d_office.id))
    assert office.name == "Главный офис"
    store = await _fresh(db, select(Store).where(Store.id == seed.s1.id))
    assert store.franchisee_id == seed.f_ip.id
    audit_rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_id == seed.filled.id, AuditLog.actor_id.is_(None)
            )
        )
    ).scalars().all()
    assert audit_rows and "position_id" in audit_rows[-1].diff
    state = await _state(tenant_id)
    assert state.last_mode == "apply" and state.pending_fingerprint is None

    # Повторный прогон — ноль изменений (приёмка каткатa).
    again = await staff_sync.sync_staff()
    second = again.hr[str(tenant_id)]
    assert second["mode"] == "apply"
    assert second["cards"] == {} and second["new_cards"] == []
    assert second["directory"]["ops"] == {}


# --- Предохранитель ---------------------------------------------------------------------


async def test_valve_holds_existing_changes_but_not_new_people_and_override_applies(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    seed = await _seed(db, tenant_id)
    hr_env(
        hr_consumer_enabled="true", hr_apply_tenants=_slug(tenant_id), hr_valve_max_cards="0"
    )
    baker = uuid.uuid4()
    newcomer = uuid.uuid4()
    rows = [
        _row(
            tenant_id,
            seed.filled.employee_id,
            _mail(tenant_id, "filled"),
            "Заполненная Карточка",
            hr=_hr(position_id=baker, site_id=seed.site_1),
        ),
        _row(
            tenant_id,
            seed.empty.employee_id,
            _mail(tenant_id, "empty"),
            "Пустая Карточка",
            hr=_hr(position_id=seed.p_barista.id),
        ),
        _row(
            tenant_id,
            newcomer,
            _mail(tenant_id, "newcomer"),
            "Новенький",
            hr=_hr(position_id=baker),
        ),
    ]
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=baker))
    _mock(monkeypatch, directory=directory, rows=rows)

    report = await staff_sync.sync_staff()
    hr_report = report.hr[str(tenant_id)]
    assert hr_report["mode"] == "blocked"
    # Изменение одной заполненной карточки; франчайзи её точки задевает её же,
    # а заполнение пустой и новичок в счёт не идут.
    assert hr_report["valve"]["cards"] == 1
    # Держим изменение заполненной карточки; новый человек и заполнение — прошли.
    assert (await _card(db, seed.filled.id)).position_id == seed.p_barista.id
    assert (await _card(db, seed.empty.id)).position_id == seed.p_barista.id
    new_card = await _fresh(
        db, select(EmployeeProfile).where(EmployeeProfile.employee_id == newcomer)
    )
    assert new_card.position_id == baker  # строка справочника для новичка создана
    state = await _state(tenant_id)
    assert state.pending_fingerprint and state.pending_ops["counts"]["cards"] == 1

    # Обход с чужим отпечатком — отказ; с верным — применяется ровно набор.
    run = hr_sync.TenantRun(
        tenant_id=tenant_id,
        tenant_slug=_slug(tenant_id),
        fetched_at=datetime.now(UTC),
        directory=_directory(tenant_id, **_dir_rows(seed, new_position=baker)),
        rows=rows,
        override_fingerprint="0" * 64,
    )
    with pytest.raises(hr_sync.OverrideRejected):
        await hr_sync.run_tenant(run)
    run.override_fingerprint = state.pending_fingerprint
    run.fetched_at = datetime.now(UTC)
    result = await hr_sync.run_tenant(run)
    assert result.report["mode"] == "apply"
    assert (await _card(db, seed.filled.id)).position_id == baker
    after = await _state(tenant_id)
    assert after.pending_fingerprint is None
    override_audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "hr_override"))
    ).scalars().all()
    assert len(override_audit) == 1


# --- Правило K --------------------------------------------------------------------------


async def test_deactivation_archive_return_and_release(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants=_slug(tenant_id))
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=uuid.uuid4()))
    card = seed.filled
    block = _hr(position_id=seed.p_barista.id, site_id=seed.site_1)

    def rows(active: bool, name: str = "Заполненная Карточка") -> list[dict]:
        email = _mail(tenant_id, "filled")
        return [_row(tenant_id, card.employee_id, email, name, is_active=active, hr=block)]

    _mock(monkeypatch, directory=directory, rows=rows(False))
    for _ in range(3):
        await staff_sync.sync_staff()
    # Три прогона подряд, но меньше 25 минут с первого наблюдения — рано.
    assert (await _card(db, card.id)).status == "active"
    shadow = await _fresh(
        db, select(ShadowUser).where(ShadowUser.employee_id == card.employee_id)
    )
    assert shadow.inactive_runs == 3
    shadow.inactive_since = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()

    report = await staff_sync.sync_staff()
    assert report.hr[str(tenant_id)]["applied"]["k"] == {"archive": [str(card.id)]}
    archived = await _card(db, card.id)
    assert archived.status == "archived" and archived.archive_reason == "auth_deactivated"
    assert archived.employee_id == card.employee_id  # вход сохранён
    assert archived.auth_deactivated_name == "Заполненная Карточка"
    archived.inactivity_warned_at = datetime.now(UTC) - timedelta(days=100)
    await db.commit()

    # Учётку включили — то же имя, другой порядок слов: карточка возвращается.
    _mock(monkeypatch, directory=directory, rows=rows(True, "Карточка Заполненная"))
    report = await staff_sync.sync_staff()
    assert report.hr[str(tenant_id)]["applied"]["k"] == {"return": [str(card.id)]}
    back = await _card(db, card.id)
    assert back.status == "active" and back.inactivity_warned_at is None

    # Аварийный рычаг: несовпадение имени = другой человек (так было до выката
    # auth 25.09, когда приглашение оживляло отключённую учётку).
    hr_env(
        hr_consumer_enabled="true",
        hr_apply_tenants=_slug(tenant_id),
        hr_release_on_name_mismatch="true",
    )
    # Снова отключили → архив; включили под ДРУГИМ именем → другой человек.
    shadow = await _fresh(
        db, select(ShadowUser).where(ShadowUser.employee_id == card.employee_id)
    )
    shadow.inactive_runs, shadow.inactive_since = 5, datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    _mock(monkeypatch, directory=directory, rows=rows(False))
    await staff_sync.sync_staff()
    # Фид переименовал архивную карточку в нового человека (как `_apply_rename`).
    renamed = await _card(db, card.id)
    renamed.full_name = "Новый Человек"
    await db.commit()
    _mock(monkeypatch, directory=directory, rows=rows(True, "Новый Человек"))
    report = await staff_sync.sync_staff()
    assert report.hr[str(tenant_id)]["applied"]["k"] == {"release": [str(card.id)]}
    released = await _card(db, card.id)
    assert released.status == "archived" and released.employee_id is None
    assert released.archive_reason == "auth_deleted"
    assert released.full_name == "Заполненная Карточка"  # история — прежнего человека


# --- Состояние и порядок прогонов ----------------------------------------------------------


async def test_failed_snapshot_keeps_freeze_and_older_run_is_skipped(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants="")
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=uuid.uuid4()))
    _mock(monkeypatch, directory=directory, rows=[])
    await staff_sync.sync_staff()
    assert (await _state(tenant_id)).authoritative is True

    # Снимка нет (403/сеть/неполный) — заморозка остаётся.
    _mock(monkeypatch, directory=None, rows=[])
    await staff_sync.sync_staff()
    assert (await _state(tenant_id)).authoritative is True

    # Прогон со снимком старше обработанного — пропуск (кнопка и воркер подряд).
    older = datetime.now(UTC) - timedelta(minutes=5)
    assert await hr_sync.write_freeze_state(tenant_id, fetched_at=older, directory=None) is False


async def test_hr_mode_null_unfreezes(db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env):
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants="")
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=uuid.uuid4()))
    _mock(monkeypatch, directory=directory, rows=[])
    await staff_sync.sync_staff()
    assert (await _state(tenant_id)).authoritative is True
    # Откат в auth (hr_mode=shadow/NULL): тенанта нет в полном снимке.
    empty = parse_directory(
        {
            "tenants": [],
            "positions": [],
            "departments": [],
            "franchisees": [],
            "site_franchisees": [],
            "totals": {"positions": 0, "departments": 0, "franchisees": 0, "site_franchisees": 0},
        }
    )
    _mock(monkeypatch, directory=empty, rows=[])
    await staff_sync.sync_staff()
    state = await _state(tenant_id)
    assert state.authoritative is False and state.in_snapshot is False


async def test_renamed_return_is_warned_not_released_by_default(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    """С выката auth 25.09 оживить учётку другому человеку нельзя: включение
    под другим именем — это тот же человек с новой фамилией (декрет)."""
    seed = await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants=_slug(tenant_id))
    card = seed.filled
    card_row = await _card(db, card.id)
    card_row.status = "archived"
    card_row.archive_reason = "auth_deactivated"
    card_row.archived_at = datetime.now(UTC)
    card_row.auth_deactivated_name = "Заполненная Карточка"
    await db.commit()
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=uuid.uuid4()))
    row = _row(
        tenant_id,
        card.employee_id,
        _mail(tenant_id, "filled"),
        "Заполненная Новофамильная",
        hr=_hr(position_id=seed.p_barista.id, site_id=seed.site_1),
    )
    _mock(monkeypatch, directory=directory, rows=[row])
    report = await staff_sync.sync_staff()
    k = report.hr[str(tenant_id)]["k"]
    assert k["return"] == [str(card.id)] and k["return_name_mismatch"] == [str(card.id)]
    back = await _card(db, card.id)
    assert back.status == "active" and back.employee_id == card.employee_id


# --- Кнопка обхода, окно каткатa --------------------------------------------------------


async def test_pending_view_shows_names_and_apply_endpoint_checks_fingerprint(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env
):
    from fastapi import HTTPException

    from app.api import employees as employees_api
    from app.schemas.employee import HrApplyPendingBody
    from app.services import org_directory_sync

    seed = await _seed(db, tenant_id)
    hr_env(
        hr_consumer_enabled="true", hr_apply_tenants=_slug(tenant_id), hr_valve_max_cards="0"
    )
    baker = uuid.uuid4()
    rows = [
        _row(
            tenant_id,
            seed.filled.employee_id,
            _mail(tenant_id, "filled"),
            "Заполненная Карточка",
            hr=_hr(position_id=baker, site_id=seed.site_1),
        )
    ]
    directory = _directory(tenant_id, **_dir_rows(seed, new_position=baker))
    _mock(monkeypatch, directory=directory, rows=rows)

    async def fake_directory(**kw):  # noqa: ANN003, ANN202
        return directory

    async def _noop(**kw) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(org_directory_sync, "fetch_org_directory", fake_directory)
    monkeypatch.setattr(employees_api, "enforce_rate_limit", _noop)
    await staff_sync.sync_staff()

    admin = make_principal(
        tenant_id, email=_mail(tenant_id, "boss"), role="admin", tenant_slug=_slug(tenant_id)
    )
    await _register(db, admin)
    await db.commit()
    pending = await employees_api.get_hr_pending(principal=admin, db=db)
    assert pending is not None and pending.cards == 1
    (item,) = pending.items
    assert item.full_name == "Заполненная Карточка"
    assert {c.field: (c.old, c.new) for c in item.changes}["position_id"] == ("Бариста", "Пекарь")
    assert {(d.kind, d.action, d.name, d.value) for d in pending.directory} == {
        ("store", "franchisee", "Точка 1", "ИП Иванов")
    }

    with pytest.raises(HTTPException) as err:
        await employees_api.apply_hr_pending(
            HrApplyPendingBody(fingerprint="0" * 64), principal=admin, db=db
        )
    assert err.value.status_code == 409
    result = await employees_api.apply_hr_pending(
        HrApplyPendingBody(fingerprint=pending.fingerprint), principal=admin, db=db
    )
    assert result["report"]["mode"] == "apply"
    assert (await _card(db, seed.filled.id)).position_id == baker
    assert await employees_api.get_hr_pending(principal=admin, db=db) is None


async def test_cutover_window_cli(db: AsyncSession, tenant_id: uuid.UUID, monkeypatch, hr_env):
    from app.jobs import hr_cutover

    await _seed(db, tenant_id)
    hr_env(hr_consumer_enabled="true", hr_apply_tenants="")
    assert await hr_cutover._change(_slug(tenant_id), window="open", force_unfreeze=False) == 0
    state = await _state(tenant_id)
    assert state.cutover_freeze is True and state.cutover_since is not None
    assert await hr_cutover._change(_slug(tenant_id), window="close", force_unfreeze=False) == 0
    state = await _state(tenant_id)
    assert state.cutover_freeze is False and state.cutover_since is None
    audit_rows = (
        await db.execute(select(AuditLog).where(AuditLog.action == "hr_window"))
    ).scalars().all()
    assert len([a for a in audit_rows if a.tenant_id == tenant_id]) == 2
    assert await hr_cutover._change("нет-такой", window="open", force_unfreeze=False) == 2
