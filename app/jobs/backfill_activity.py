"""One-shot: ретро-начисление рейтинга за события до Ф3b (идемпотентно).

Собирает activity_events из уже существующих фактов: ознакомления с
материалами/новостями, участия в опросах, завершённые уроки. Повторный
запуск безопасен — ON CONFLICT DO NOTHING по «первому действию».

Скан тенантов — bypass, запись — в tenant-scoped сессиях (инвариант
learn-домена). Запуск руками после деплоя Ф3b:
    .venv/bin/python -m app.jobs.backfill_activity
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select, text

from app import log as log_config
from app.db import tenant_scoped_session

log = structlog.get_logger("jobs.backfill_activity")

# (источник, событие, object_type): profile_id + object_id + occurred_at.
_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "SELECT profile_id, material_id AS object_id, acknowledged_at AS occurred_at, "
        "tenant_id FROM material_acknowledgements",
        "material.acknowledged",
        "library_material",
    ),
    (
        "SELECT profile_id, post_id AS object_id, acknowledged_at AS occurred_at, "
        "tenant_id FROM news_acknowledgements",
        "news.acknowledged",
        "news_post",
    ),
    (
        "SELECT profile_id, survey_id AS object_id, submitted_at AS occurred_at, "
        "tenant_id FROM survey_participations",
        "survey.completed",
        "survey",
    ),
    (
        "SELECT profile_id, lesson_id AS object_id, completed_at AS occurred_at, "
        "tenant_id FROM lesson_progress WHERE status = 'completed'",
        "lesson.completed",
        "course_lesson",
    ),
)


async def main() -> int:
    log_config.configure()
    from app.services.learn_settings import get_settings_dict

    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_ids = [
            r[0]
            for r in await scan.execute(
                select(text("DISTINCT tenant_id")).select_from(text("employee_profiles"))
            )
        ]

    total = 0
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(tenant_id) as session:
            settings = await get_settings_dict(session, tenant_id)
            weights = settings.get("rating_weights") or {}
            for src_sql, event_type, object_type in _SOURCES:
                points = float(weights.get(event_type, 0) or 0)
                result = await session.execute(
                    # S608: src_sql — константы из _SOURCES, не пользовательский ввод.
                    text(
                        "INSERT INTO activity_events "  # noqa: S608
                        "(tenant_id, profile_id, event_type, object_type, object_id, "
                        " points, meta, occurred_at) "
                        f"SELECT tenant_id, profile_id, :event_type, :object_type, "
                        f"object_id, :points, '{{\"backfill\": true}}'::jsonb, "
                        f"COALESCE(occurred_at, now()) FROM ({src_sql}) src "
                        "ON CONFLICT (tenant_id, profile_id, event_type, object_type, "
                        "object_id) DO NOTHING"
                    ),
                    {
                        "event_type": event_type,
                        "object_type": object_type,
                        "points": points,
                    },
                )
                total += result.rowcount or 0
            await session.commit()

    log.info("backfill_activity.finished", inserted=total, tenants=len(tenant_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
