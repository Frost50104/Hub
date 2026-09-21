"""Два рубильника шаблонов проектов: env (ops) И тенантный ключ (hub-admin).

Выключено = модуля «нет»: ручки библиотеки и копирования 404 (кроме
`settings`), страница шаблона 404, пункт меню спрятан
(`/api/me.features.project_templates`). Шаблоны остаются в БД и по-прежнему
невидимы — «замок» RLS от рубильника не зависит.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.learn_settings import get_settings_dict, set_setting

SETTING_KEY = "project_templates_enabled"


def env_enabled() -> bool:
    return bool(get_settings().project_templates_enabled)


async def tenant_enabled(db: AsyncSession, tenant_id: UUID) -> bool:
    return bool((await get_settings_dict(db, tenant_id)).get(SETTING_KEY, False))


async def templates_enabled_for(db: AsyncSession, tenant_id: UUID) -> bool:
    return env_enabled() and await tenant_enabled(db, tenant_id)


async def set_tenant_enabled(db: AsyncSession, tenant_id: UUID, enabled: bool) -> None:
    await set_setting(db, tenant_id, SETTING_KEY, bool(enabled))
