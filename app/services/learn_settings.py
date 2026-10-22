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
    # Сертификаты (ОС 19.08: «сертификат должен быть в фирменном стиле»).
    # id картинки-подложки в media_files; None — типографская рамка по умолчанию.
    "certificate_background_media_id": None,
    # Медиа (Ф3a).
    "video_max_bytes": 300 * 1024 * 1024,
    "image_max_bytes": 10 * 1024 * 1024,
    "document_max_bytes": 50 * 1024 * 1024,
    # «Гусиная гонка» (0057): тенантный рубильник модуля. Дефолт false —
    # гонка появляется только там, где её включил hub-admin.
    "race_enabled": False,
    # Шаблоны проектов (0060): тенантный рубильник модуля. Дефолт false —
    # библиотека появляется там, где её включил hub-admin. «Замок» шаблонов
    # от рубильника НЕ зависит: выключение не должно открывать их спискам.
    "project_templates_enabled": False,
    # Конвейер видео урока (0066): тенантный рубильник + настройки монтажа.
    # Дефолт false — модуль появляется там, где его включил hub-admin.
    "media_pipeline_enabled": False,
    # Каждое загруженное видео получает субтитры и попадает в поиск; чистовик
    # и монтаж — только по кнопке.
    "media_auto_transcribe": True,
    # Сцена-референс гуся 16:9 (id картинки в media_files, role='scene').
    "media_scene_media_id": None,
    # Лимит минут гуся в месяц (Hedra платная); резерв списывается при заказе.
    "media_avatar_monthly_minutes_cap": 30,
    "media_avatar_resolution": "720p",
    # Раскадровка: порог доли кадра под лицом, минимальный отрезок, склейка зазоров.
    "media_storyboard": {"face_ratio_thr": 0.12, "min_segment_sec": 4, "bridge_gap_sec": 2},
    # Чистовик: паузы длиннее порога ужимаются до keep_sec с полями margin_sec.
    "media_cleanup_defaults": {
        "min_pause_sec": 1.5,
        "keep_sec": 0.7,
        "margin_sec": 0.2,
        "denoise": "afftdn",
        "loudnorm_i": -16,
        "loudnorm_tp": -1.5,
        "loudnorm_lra": 11,
        "fps_cap": 30,
        "scale_cap": 1080,
    },
    # Слова для initial_prompt Whisper: названия, аббревиатуры, точки.
    "media_glossary": "Signaris, Hub",
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
    # Явные CAST, а НЕ `:v::jsonb`: SQLAlchemy не признаёт биндом параметр, за
    # которым сразу идёт двоеточие (regex-lookahead), и `:v` уезжал в SQL как
    # литерал — «syntax error at or near ":"». Ключу CAST нужен отдельно:
    # в `ARRAY[:k]` Postgres не выводит тип элемента. Функция была написана
    # про запас и до сертификатов (ОС 19.08) не вызывалась ни разу — поэтому
    # ошибка дожила до первого вызова.
    await db.execute(
        text(
            "INSERT INTO learning_settings (tenant_id, data) "
            "VALUES (CAST(:t AS uuid), jsonb_build_object(CAST(:k AS text), CAST(:v AS jsonb))) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "data = jsonb_set(learning_settings.data, ARRAY[CAST(:k AS text)], "
            "CAST(:v AS jsonb), true), "
            "updated_at = now()"
        ),
        {"t": str(tenant_id), "k": key, "v": _to_json(value)},
    )


def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
