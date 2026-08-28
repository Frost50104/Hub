"""Имя и email сотрудника принадлежат auth; профиль их зеркалит.

ОС 28.08: HR переименовал человека на экране «Сотрудники», а в пикере
участников осталось старое имя — трекер читает `shadow_users`, learn читает
`employee_profiles`, и хозяева у них были разные. Синхронизация из auth в
профиль существовала, но переносила только email; ни она, ни правка полей в
редакторе не были покрыты ни одним тестом.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from fastapi import HTTPException
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.employees import create_employee, update_employee
from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.services.employee_profiles import ensure_profile_for_principal
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _admin(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """hub-admin: экран «Сотрудники» открыт только ему."""
    principal = make_principal(tenant_id, email=f"admin-{slug}@t.ru", tenant_slug=slug)
    principal.product_roles["hub"] = "admin"
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    return principal


async def _login(db: AsyncSession, principal) -> EmployeeProfile:
    """Вход человека: shadow + матчинг/создание профиля."""
    await upsert_shadow_user(db, principal, table="shadow_users")
    result = await ensure_profile_for_principal(db, principal)
    await db.commit()
    assert result.profile is not None
    await db.refresh(result.profile)
    return result.profile


async def test_login_syncs_new_name_into_profile(db: AsyncSession, tenant_id: uuid.UUID):
    """Переименовали в auth → при входе имя приезжает в профиль.

    Это и есть починка исходной жалобы: списки «Обучения» читают профиль.
    """
    person = make_principal(
        tenant_id, email="sync1@t.ru", full_name="Скробот Мария", tenant_slug="idn1"
    )
    profile = await _login(db, person)
    assert profile.full_name == "Скробот Мария"

    # Principal — frozen dataclass: следующий вход приходит НОВЫМ токеном с тем
    # же employee_id и другим именем.
    renamed = dataclasses.replace(person, full_name="HR Пользователь")
    profile = await _login(db, renamed)
    assert profile.full_name == "HR Пользователь"

    # Смена имени — событие, которое хочется видеть в журнале, как и смена email.
    rows = (
        await db.execute(
            select(AuditLog.diff).where(
                AuditLog.object_type == "employee_profile",
                AuditLog.object_id == profile.id,
            )
        )
    ).scalars().all()
    assert any("full_name" in (d or {}) for d in rows)


async def test_empty_name_in_token_does_not_wipe_profile(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Пустое имя из токена не затирает существующее.

    `full_name` приходит из внешнего JWT, а в профиле это единственный
    опознавательный признак в списках: пустое значение сделало бы человека
    безымянным во всём learn-домене.
    """
    person = make_principal(
        tenant_id, email="sync2@t.ru", full_name="Иванов Иван", tenant_slug="idn2"
    )
    await _login(db, person)

    blank = dataclasses.replace(person, full_name="   ")
    profile = await _login(db, blank)
    assert profile.full_name == "Иванов Иван"


async def test_patch_rejects_changed_name_after_first_login(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Правка имени у заходившего — 422, а не молчаливая потеря.

    Без гейта правка принималась бы и исчезала при следующем входе человека.
    """
    admin = await _admin(db, tenant_id, "idn3")
    person = make_principal(
        tenant_id, email="sync3@t.ru", full_name="Петров Пётр", tenant_slug="idn3"
    )
    profile = await _login(db, person)

    with pytest.raises(HTTPException) as exc:
        await update_employee(profile.id, EmployeeUpdate(full_name="Другое Имя"), admin, db)
    assert exc.value.status_code == 422
    assert "auth" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await update_employee(profile.id, EmployeeUpdate(email="other@t.ru"), admin, db)
    assert exc.value.status_code == 422


async def test_patch_with_same_name_still_works(db: AsyncSession, tenant_id: uuid.UUID):
    """Форма редактора шлёт объект ЦЕЛИКОМ — включая неизменённое имя.

    Гейт «поле присутствует» сломал бы сохранение должности и роли: и у нового
    бандла, и у вчерашнего, который живёт в PWA до применения обновления.
    """
    admin = await _admin(db, tenant_id, "idn4")
    person = make_principal(
        tenant_id, email="sync4@t.ru", full_name="Сидоров Сидор", tenant_slug="idn4"
    )
    profile = await _login(db, person)

    updated = await update_employee(
        profile.id,
        EmployeeUpdate(
            full_name="Сидоров Сидор",  # то же самое
            email="sync4@t.ru",  # то же самое
            org_role="office",
        ),
        admin,
        db,
    )
    assert updated.org_role == "office"
    assert updated.full_name == "Сидоров Сидор"


async def test_card_without_login_is_still_editable(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Карточку того, кто ещё не заходил, HR правит как раньше.

    Критерий гейта — `last_activity_at`, а не наличие `employee_id`: ручки
    /link и /restore привязывают аккаунт без входа, и по employee_id карточка
    замерзала бы с HR-именем, которое уже некому исправить.
    """
    admin = await _admin(db, tenant_id, "idn5")
    created = await create_employee(
        EmployeeCreate(email="future@t.ru", full_name="Будущий Сотрудник"), admin, db
    )
    assert created.last_activity_at is None

    updated = await update_employee(
        created.id, EmployeeUpdate(full_name="Исправленное Имя"), admin, db
    )
    assert updated.full_name == "Исправленное Имя"

