"""Настройки learn-домена: дефолты + по-ключевое обновление (jsonb_set).

Читается как «дефолты, перекрытые сохранённым JSONB». Запись — ТОЛЬКО
по-ключево: два админа, правящие разные ключи, не затирают друг друга.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULTS: dict[str, Any] = {
    # Правило неактивности (ТЗ §23): предупреждение спустя N дней тишины,
    # авто-архив спустя grace-период после предупреждения.
    "inactivity_warn_days": 90,
    "inactivity_archive_grace_days": 3,
    "inactivity_warn_text": (
        "Подтвердите, что вы ещё с нами: войдите в Hub. Если активность не "
        "будет подтверждена в течение {grace_days} дней, аккаунт будет "
        "переведён в архив."
    ),
    # Анонимные опросы (Ф2): минимальный размер среза.
    "survey_k_anonymity": 5,
    # Рейтинг (Ф3b): веса activity-событий.
    "rating_weights": {
        "lesson.completed": 1,
        "quiz.passed": 1,
        "quiz.passed_retry": 0.5,
        "quiz.perfect_bonus": 0,
        "product.first_view": 0.5,
        "material.acknowledged": 0.5,
        "survey.completed": 0.5,
        "news.acknowledged": 0,
        "login.daily": 0,
    },
    # Медиа (Ф3a).
    "video_max_bytes": 300 * 1024 * 1024,
    "image_max_bytes": 10 * 1024 * 1024,
    "document_max_bytes": 50 * 1024 * 1024,
}

_ALLOWED_KEYS = frozenset(DEFAULTS)


async def get_settings_dict(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    row = (
        await db.execute(
            text("SELECT data FROM learning_settings WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
    ).scalar_one_or_none()
    merged = dict(DEFAULTS)
    if row:
        merged.update(row)
    return merged


async def set_setting(db: AsyncSession, tenant_id: UUID, key: str, value: Any) -> None:
    """UPSERT одного ключа через jsonb_set — не перезаписывает соседние."""
    if key not in _ALLOWED_KEYS:
        raise ValueError(f"Неизвестный ключ настройки: {key!r}")
    await db.execute(
        text(
            "INSERT INTO learning_settings (tenant_id, data) "
            "VALUES (:t, jsonb_build_object(:k, :v::jsonb)) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "data = jsonb_set(learning_settings.data, ARRAY[:k], :v::jsonb, true), "
            "updated_at = now()"
        ),
        {"t": str(tenant_id), "k": key, "v": _to_json(value)},
    )


def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
