"""Тема оформления принадлежит учётной записи, а не браузеру.

Регрессия ОС 09.09: на общем устройстве A выбирал светлую тему, выходил, а
входящий B получал ту же светлую — тема жила только в localStorage.

Проверяем: `/me` отдаёт тему, `PUT /me/preferences` её сохраняет идемпотентно,
работает у principal БЕЗ hub-роли (у него нет учебной карточки, а тему он
видит), строка изолирована по тенанту и уходит каскадом вместе с тенью.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from signaris_auth import Principal
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.me import MePreferencesUpdate, get_me, put_my_preferences
from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile
from app.models.user_preference import UserPreference
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _member(
    db: AsyncSession, tenant_id: uuid.UUID, slug: str, *, org_role: str | None = "office"
) -> Principal:
    principal = make_principal(tenant_id, email=f"{slug}@t.ru", tenant_slug=slug)
    await _register(db, principal, org_role=org_role)
    return principal


async def test_me_theme_is_none_for_new_user(db, tenant_id):
    """None — «выбора нет». Фронт по нему решает, можно ли засеять локальный."""
    principal = await _member(db, tenant_id, "pref-new")
    assert (await get_me(principal=principal, db=db)).theme is None


async def test_put_theme_persists_and_me_returns_it(db, tenant_id):
    principal = await _member(db, tenant_id, "pref-put")
    result = await put_my_preferences(
        MePreferencesUpdate(theme="light"), principal=principal, db=db
    )
    assert result.theme == "light"
    assert (await get_me(principal=principal, db=db)).theme == "light"


async def test_put_theme_is_upsert(db, tenant_id):
    """Вторая запись меняет строку, а не заводит вторую (PK — employee_id)."""
    principal = await _member(db, tenant_id, "pref-upsert")
    await put_my_preferences(
        MePreferencesUpdate(theme="light"), principal=principal, db=db
    )
    await put_my_preferences(
        MePreferencesUpdate(theme="dark"), principal=principal, db=db
    )
    rows = await db.scalar(
        select(func.count()).select_from(UserPreference).where(
            UserPreference.employee_id == principal.employee_id
        )
    )
    assert rows == 1
    assert (await get_me(principal=principal, db=db)).theme == "dark"


async def test_theme_works_without_hub_role(db, tenant_id):
    """Юзер другого продукта Signaris видит `NoAccessScreen` — но внутри Shell.

    Тема ему доступна: ручка стоит на `require_auth_any()`, а хранилище ключуется
    тенью, которая есть у любого аутентифицированного principal. Учебной
    карточки при этом не появляется — её создаёт только ветка с hub-ролью.
    """
    principal = Principal(
        employee_id=uuid.uuid4(),
        email="desk-only@t.ru",
        tenant_id=tenant_id,
        tenant_slug="pref-norole",
        full_name="Дэск Юзер",
        product_roles={"desk": "member"},
        jti=str(uuid.uuid4()),
    )
    await _register(db, principal)

    await put_my_preferences(
        MePreferencesUpdate(theme="dark"), principal=principal, db=db
    )
    me = await get_me(principal=principal, db=db)
    assert me.hub_role is None
    assert me.theme == "dark"
    assert me.profile is None
    profiles = await db.scalar(
        select(func.count()).select_from(EmployeeProfile).where(
            EmployeeProfile.employee_id == principal.employee_id
        )
    )
    assert profiles == 0


def test_unknown_theme_is_rejected_by_schema():
    """Значение сверх пары — 422 схемой, до похода в БД (там ещё и CHECK)."""
    with pytest.raises(ValidationError):
        MePreferencesUpdate(theme="solarized")


async def test_theme_is_tenant_isolated(rls_enforced):
    """Под non-superuser ролью чужая строка не видна — политика реально работает."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    employee_id = uuid.uuid4()
    async with tenant_scoped_session(None, bypass_rls=True) as s:
        for tid in (tenant_a, tenant_b):
            await s.execute(
                text(
                    "INSERT INTO shadow_tenants (id, slug, name, status) "
                    "VALUES (:tid, :slug, 'T', 'active') ON CONFLICT (id) DO NOTHING"
                ),
                {"tid": tid, "slug": f"t-{tid.hex[:12]}"},
            )
        await s.execute(
            text(
                "INSERT INTO shadow_users (employee_id, tenant_id, email, full_name) "
                "VALUES (:eid, :tid, :email, 'N')"
            ),
            {"eid": employee_id, "tid": tenant_a, "email": f"{employee_id.hex[:8]}@t.ru"},
        )
        await s.execute(
            text(
                "INSERT INTO user_preferences (employee_id, tenant_id, theme) "
                "VALUES (:eid, :tid, 'light')"
            ),
            {"eid": employee_id, "tid": tenant_a},
        )
        await s.commit()

    async with tenant_scoped_session(tenant_a) as s:
        assert await s.scalar(
            select(UserPreference.theme).where(
                UserPreference.employee_id == employee_id
            )
        ) == "light"

    async with tenant_scoped_session(tenant_b) as s:
        assert (
            await s.scalar(
                select(UserPreference.theme).where(
                    UserPreference.employee_id == employee_id
                )
            )
            is None
        )


async def test_row_dies_with_the_shadow_user(db, tenant_id):
    """ON DELETE CASCADE: настройка не переживает удаление сотрудника."""
    principal = await _member(db, tenant_id, "pref-cascade")
    await put_my_preferences(
        MePreferencesUpdate(theme="light"), principal=principal, db=db
    )
    await db.execute(
        text("DELETE FROM shadow_users WHERE employee_id = :eid"),
        {"eid": principal.employee_id},
    )
    await db.commit()
    left = await db.scalar(
        select(func.count()).select_from(UserPreference).where(
            UserPreference.employee_id == principal.employee_id
        )
    )
    assert left == 0
