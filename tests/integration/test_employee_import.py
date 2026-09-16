"""CSV-импорт сотрудников: только ОБНОВЛЕНИЕ существующих карточек (16.09).

Решение владельца: auth — единственный источник штата, ручное заведение и
создание карточек импортом закрыты. Строка без активной карточки — построчная
ошибка, и до справочников она не доходит. Контракт 05.09 (задача auth
import_no_autocreate) не менялся: магазины НЕ автосоздаются (неизвестный —
ошибка с замороженным текстом), должности/отделы/франчайзи создаются.

ВАЖНО про прямой вызов ручки: `dry_run`/`create_missing_refs`/
`suppress_automations` объявлены `Query(default=…)` — без явной передачи
в аргумент попадёт truthy Query-ОБЪЕКТ, и тест проверял бы не ту ветку.
Передаём все три всегда (тот же паттерн — test_tasks_import.py).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api import employees as employees_api
from app.api.employees import import_employees
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.models.shadow import ShadowUser
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Рейт-лимит импорта ходит в Redis, которого в integration-тестах нет."""

    async def _noop(**kw) -> None:
        return None

    monkeypatch.setattr(employees_api, "enforce_rate_limit", _noop)


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="import.csv")


async def _run(db: AsyncSession, tenant_id: uuid.UUID, csv_text: str, **kw):
    admin = make_principal(tenant_id=tenant_id, role="admin")
    # FK employee_profiles.created_by / audit → shadow_users: тень актёра обязана быть.
    if await db.get(ShadowUser, admin.employee_id) is None:
        db.add(
            ShadowUser(
                employee_id=admin.employee_id,
                tenant_id=tenant_id,
                email="importer@t.ru",
                full_name="Импортёр",
            )
        )
        await db.flush()
    return await import_employees(
        file=_upload(csv_text),
        dry_run=kw.pop("dry_run", False),
        create_missing_refs=kw.pop("create_missing_refs", False),
        suppress_automations=True,
        principal=admin,
        db=db,
    )


async def _card(db: AsyncSession, tenant_id: uuid.UUID, email: str, **fields) -> EmployeeProfile:
    card = EmployeeProfile(
        tenant_id=tenant_id, email=email, full_name=fields.pop("full_name", "Сотрудник"), **fields
    )
    db.add(card)
    await db.flush()
    return card


async def _profile(db: AsyncSession, email: str) -> EmployeeProfile | None:
    return (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.email == email))
    ).scalar_one_or_none()


async def test_unknown_store_is_row_error_and_not_created(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Неизвестный магазин — построчная ошибка с замороженным текстом (05.09);
    магазин не создан, карточка не тронута."""
    card = await _card(db, tenant_id, "new1@t.ru")
    report = await _run(
        db,
        tenant_id,
        "email;full_name;store\nnew1@t.ru;Новая Сотрудница;Пушкина 14\n",
    )
    assert report.updated == 0
    assert report.errors == ["Строка 2: Магазин «Пушкина 14» не найден"]

    store = (
        await db.execute(select(Store).where(Store.name == "Пушкина 14"))
    ).scalar_one_or_none()
    assert store is None
    await db.refresh(card)
    assert card.store_id is None


async def test_unknown_position_still_autocreates(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Должности (как отделы и франчайзи) создаются как раньше и присваиваются
    существующей карточке — онбординг по CSV жив, просто карточка уже есть."""
    card = await _card(db, tenant_id, "new2@t.ru")
    report = await _run(
        db,
        tenant_id,
        "email;full_name;position\nnew2@t.ru;Новый Сотрудник;Бариста-наставник\n",
    )
    assert report.updated == 1 and report.skipped == 0 and report.errors == []

    position = (
        await db.execute(select(Position).where(Position.name == "Бариста-наставник"))
    ).scalar_one()
    await db.refresh(card)
    assert card.position_id == position.id


async def test_explicit_flag_still_creates_store(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """API-люк сохранён: явный create_missing_refs=true создаёт магазин.
    UI флаг не передаёт — дефолт сервера и есть поведение интерфейса."""
    card = await _card(db, tenant_id, "new3@t.ru")
    report = await _run(
        db,
        tenant_id,
        "email;full_name;store\nnew3@t.ru;Со Складом;Новый Склад\n",
        create_missing_refs=True,
    )
    assert report.updated == 1 and report.errors == []
    store = (
        await db.execute(select(Store).where(Store.name == "Новый Склад"))
    ).scalar_one()
    assert store.code is None  # автосозданный — голый: только tenant_id и name
    await db.refresh(card)
    assert card.store_id == store.id


async def test_row_without_card_is_skipped_and_creates_nothing(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Карточек импорт не заводит: строка без карточки — ошибка, счётчик
    `skipped`, и ни профиля, ни должности за ней не появляется — проверка
    карточки стоит раньше справочников."""
    report = await _run(
        db,
        tenant_id,
        "email;full_name;position\nnobody@t.ru;Никто Никтович;Должность Из Ниоткуда\n",
    )
    assert report.updated == 0 and report.skipped == 1
    assert report.errors == [
        "Строка 2: карточки с email «nobody@t.ru» нет — учётные записи заводятся в auth"
    ]
    assert await _profile(db, "nobody@t.ru") is None
    position = (
        await db.execute(select(Position).where(Position.name == "Должность Из Ниоткуда"))
    ).scalar_one_or_none()
    assert position is None


async def test_archived_card_row_names_the_archive(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Архивная карточка с этой почтой — отдельная ошибка: «заводится в auth»
    про неё было бы неправдой, её надо восстановить."""
    await _card(
        db,
        tenant_id,
        "gone@t.ru",
        status="archived",
        archived_at=datetime.now(UTC),
        archive_reason="manual",
    )
    report = await _run(db, tenant_id, "email;position\ngone@t.ru;Бариста\n")
    assert report.updated == 0 and report.skipped == 1
    assert report.errors == ["Строка 2: карточка с email «gone@t.ru» в архиве — восстановите её"]


async def test_empty_cells_keep_values_and_name_is_not_overwritten(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Частичный файл: пустые ячейки поля не трогают (ТУ не становится
    линейным, дата найма не обнуляется), а `full_name` из CSV не пишется —
    имя принадлежит auth."""
    card = await _card(
        db,
        tenant_id,
        "tu@t.ru",
        full_name="Терентьева Ульяна",
        org_role="tu",
        hired_at=date(2025, 3, 1),
    )
    report = await _run(
        db,
        tenant_id,
        "email;full_name;phone;org_role;hired_at\ntu@t.ru;Другое Имя;+7 900 000-00-00;;\n",
    )
    assert report.updated == 1 and report.errors == []
    await db.refresh(card)
    assert card.full_name == "Терентьева Ульяна"
    assert card.org_role == "tu"
    assert card.hired_at == date(2025, 3, 1)
    assert card.phone == "+7 900 000-00-00"


async def test_unchanged_row_is_not_counted_as_updated(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Строка, которая ничего не меняет, в `updated` не попадает — иначе отчёт
    «обновлено 200» на файле без изменений выглядел бы как массовая правка."""
    await _card(db, tenant_id, "same@t.ru", phone="+7 111")
    report = await _run(db, tenant_id, "email;phone\nsame@t.ru;+7 111\n")
    assert report.updated == 0 and report.skipped == 0 and report.errors == []


async def test_dry_run_changes_nothing(db: AsyncSession, tenant_id: uuid.UUID):
    """«Проверить» считает, но не пишет: карточка после отката прежняя."""
    card = await _card(db, tenant_id, "dry@t.ru")
    await db.commit()  # сид переживает rollback dry-run
    report = await _run(db, tenant_id, "email;phone\ndry@t.ru;+7 222\n", dry_run=True)
    assert report.dry_run is True and report.updated == 1
    await db.refresh(card)
    assert card.phone is None
