"""Рубильники конвейера видео: env (ops) И тенантный ключ (hub-admin).

Выключено = модуля «нет»: ручки конвейера 404 (админские настройки — 404 по
env, 409 по тенанту), кнопок в редакторе нет (`/api/me.features`), MOV/WebM
не принимаются, воркер спит, субтитры в плеере не отдаются. Данные остаются —
включение возвращает всё.

Гусь — третий, отдельный выключатель: `media_avatar_enabled` И ключ Hedra.
Staging ходит в Hedra за реальные деньги только с явного флага.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.learn_settings import get_settings_dict, set_setting

SETTING_KEY = "media_pipeline_enabled"


def env_enabled() -> bool:
    return bool(get_settings().media_pipeline_enabled)


def avatar_env_enabled() -> bool:
    """Гусь возможен на этом сервере: модуль включён, флаг аватара и ключ Hedra есть."""
    s = get_settings()
    return env_enabled() and bool(s.media_avatar_enabled) and bool(s.hedra_api_key)


def stt_configured() -> bool:
    """Расшифровка длинных файлов настроена: удалённый провайдер с ключом и
    адресом, либо локальный с ЯВНЫМ `media_stt_url` (дефолта нет нарочно)."""
    s = get_settings()
    if s.media_stt_provider == "openai":
        return bool(s.media_stt_api_key and s.media_stt_base_url)
    return bool(s.media_stt_url)


async def tenant_enabled(db: AsyncSession, tenant_id: UUID) -> bool:
    return bool((await get_settings_dict(db, tenant_id)).get(SETTING_KEY, False))


async def pipeline_enabled_for(db: AsyncSession, tenant_id: UUID) -> bool:
    return env_enabled() and await tenant_enabled(db, tenant_id)


async def avatar_enabled_for(db: AsyncSession, tenant_id: UUID) -> bool:
    return avatar_env_enabled() and await tenant_enabled(db, tenant_id)


async def set_tenant_enabled(db: AsyncSession, tenant_id: UUID, enabled: bool) -> None:
    await set_setting(db, tenant_id, SETTING_KEY, bool(enabled))
