"""Два рубильника «Гусиной гонки»: env (ops) И тенантный ключ (hub-admin).

Выключено = модуля «нет»: пользовательские ручки 404, публичная ссылка 404,
пункт меню и маршруты спрятаны (`/api/me.features.race`), джобы пропускают
тенант, пуши не уходят. Данные не удаляются — включение возвращает всё.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.learn_settings import get_settings_dict, set_setting

SETTING_KEY = "race_enabled"


def env_enabled() -> bool:
    return bool(get_settings().race_enabled)


def sync_enabled() -> bool:
    """Обращения к iiko и пуши гонки (staging — всегда выключено)."""
    return env_enabled() and bool(get_settings().race_sync_enabled)


async def tenant_enabled(db: AsyncSession, tenant_id: UUID) -> bool:
    return bool((await get_settings_dict(db, tenant_id)).get(SETTING_KEY, False))


async def race_enabled_for(db: AsyncSession, tenant_id: UUID) -> bool:
    return env_enabled() and await tenant_enabled(db, tenant_id)


async def set_tenant_enabled(db: AsyncSession, tenant_id: UUID, enabled: bool) -> None:
    await set_setting(db, tenant_id, SETTING_KEY, bool(enabled))
