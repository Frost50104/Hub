"""CSV-импорт сотрудников: магазины НЕ автосоздаются (задача auth 05.09).

Опечатка в названии магазина бесшумно порождала магазин-дубль без кода и
адреса (три таких «сироты» от 28.08 живут на проде). Должности/отделы/
франчайзи автосоздаваться ОБЯЗАНЫ — на этом стоит онбординг.

ВАЖНО про прямой вызов ручки: `dry_run`/`create_missing_refs`/
`suppress_automations` объявлены `Query(default=…)` — без явной передачи
в аргумент попадёт truthy Query-ОБЪЕКТ, и тест проверял бы не ту ветку.
Передаём все три всегда (тот же паттерн — test_tasks_import.py).
"""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.employees import import_employees
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.models.shadow import ShadowUser
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="import.csv")


async def _run(db: AsyncSession, tenant_id: uuid.UUID, csv_text: str, **kw):
    admin = make_principal(tenant_id=tenant_id, role="admin")
    # FK employee_profiles.created_by -> shadow_users: тень актёра обязана быть.
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


async def test_unknown_store_is_row_error_and_not_created(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Неизвестный магазин — построчная ошибка; ни магазина, ни профиля."""
    report = await _run(
        db,
        tenant_id,
        "email;full_name;store\nnew1@t.ru;Новая Сотрудница;Пушкина 14\n",
    )
    assert report.created == 0
    assert report.errors == ["Строка 2: Магазин «Пушкина 14» не найден"]

    store = (
        await db.execute(select(Store).where(Store.name == "Пушкина 14"))
    ).scalar_one_or_none()
    assert store is None
    profile = (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "new1@t.ru")
        )
    ).scalar_one_or_none()
    assert profile is None


async def test_unknown_position_still_autocreates(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Должности (как отделы и франчайзи) создаются как раньше — онбординг жив."""
    report = await _run(
        db,
        tenant_id,
        "email;full_name;position\nnew2@t.ru;Новый Сотрудник;Бариста-наставник\n",
    )
    assert report.created == 1 and report.errors == []

    position = (
        await db.execute(select(Position).where(Position.name == "Бариста-наставник"))
    ).scalar_one()
    profile = (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "new2@t.ru")
        )
    ).scalar_one()
    assert profile.position_id == position.id


async def test_explicit_flag_still_creates_store(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """API-люк сохранён: явный create_missing_refs=true создаёт магазин.
    UI флаг не передаёт — дефолт сервера и есть поведение интерфейса."""
    report = await _run(
        db,
        tenant_id,
        "email;full_name;store\nnew3@t.ru;Со Складом;Новый Склад\n",
        create_missing_refs=True,
    )
    assert report.created == 1 and report.errors == []
    store = (
        await db.execute(select(Store).where(Store.name == "Новый Склад"))
    ).scalar_one()
    assert store.code is None  # автосозданный — голый: только tenant_id и name
