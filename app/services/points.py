"""Начисление баллов рейтинга (Ф3b, ТЗ §7).

`award()` — единственная точка записи в activity_events. Идемпотентность —
partial-unique (tenant, profile, event_type, object_type, object_id) +
ON CONFLICT DO NOTHING: повторное прохождение того же объекта не даёт
второго начисления («первое действие»).

points — СНАПШОТ веса из learning_settings.rating_weights на момент
события; правка весов историю не пересчитывает (осознанно, UI поясняет).
Вес 0 — событие всё равно пишется (история активности для аналитики Ф5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.services.learn_settings import get_settings_dict

log = structlog.get_logger("points")


async def award(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    profile_id: UUID,
    event_type: str,
    object_type: str,
    object_id: UUID,
    weight_key: str | None = None,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Начислить событие. → True, если записано (не дубль).

    weight_key — ключ веса, если отличается от event_type
    (quiz.passed с attempt_no>1 → вес 'quiz.passed_retry').
    """
    settings = await get_settings_dict(db, tenant_id)
    weights = settings.get("rating_weights") or {}
    try:
        points = float(weights.get(weight_key or event_type, 0) or 0)
    except (TypeError, ValueError):
        points = 0.0
    if points < 0:
        points = 0.0  # отрицательные веса запрещены (валидация настроек)

    stmt = pg_insert(ActivityEvent).values(
        tenant_id=tenant_id,
        profile_id=profile_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        points=points,
        meta=meta,
    )
    result = await db.execute(
        stmt.on_conflict_do_nothing(
            index_elements=[
                "tenant_id",
                "profile_id",
                "event_type",
                "object_type",
                "object_id",
            ]
        )
    )
    created = bool(result.rowcount)
    if created:
        log.info(
            "points.awarded",
            event_type=event_type,
            object_id=str(object_id),
            points=points,
        )
    return created
