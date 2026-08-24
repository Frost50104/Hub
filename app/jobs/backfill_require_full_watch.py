"""One-shot: включить гейт досмотра там, где импорт забыл ключ.

Импорт контента 2026-08-16 строил видео-ноды без `requireFullWatch`, и для
сервера это то же самое, что `false` (`collect_required_videos`): урок,
состоящий из ролика, засчитывался нажатием кнопки. Ноды с ЯВНЫМ `false`
не трогаем — их печатаем отдельным списком, решение по ним за владельцем.

Окно закрывается само: редактор урока материализует дефолты схемы, и первое
же сохранение впечатывает явный `false`. Поэтому прогонять сразу после
выката, а не «когда-нибудь».

    .venv/bin/python -m app.jobs.backfill_require_full_watch            # разбор
    .venv/bin/python -m app.jobs.backfill_require_full_watch --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.course import CourseLesson
from app.models.progress import LessonProgress
from app.services import audit
from app.services.lesson_content import transform_nodes, validate_lesson_content

log = structlog.get_logger("jobs.backfill_require_full_watch")

FLAG = "requireFullWatch"
# audit_log.action — VARCHAR(32): длинное имя роняло весь прогон на commit
# (StringDataRightTruncationError), причём после всей работы. Регресс — в
# tests/unit/test_backfill_require_full_watch.py.
AUDIT_ACTION = "watch_gate_backfill"


def ensure_require_full_watch(payload: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """→ (новый payload, проставлено ключей, пропущено из-за явного false).

    Исходник не мутируется: `transform_nodes` работает на глубокой копии, и
    это важно — иначе SQLAlchemy не увидит смены значения JSONB (объект тот
    же) и не запишет ничего.
    """
    counters = {"added": 0, "explicit": 0}

    def fn(node: dict[str, Any]) -> None:
        if node.get("type") != "video":
            return
        attrs = node.get("attrs")
        if not isinstance(attrs, dict):
            attrs = {}
            node["attrs"] = attrs
        if FLAG in attrs:
            if not attrs[FLAG]:
                counters["explicit"] += 1
            return
        attrs[FLAG] = True
        counters["added"] += 1
        return

    patched = transform_nodes(payload, fn)
    return patched, counters["added"], counters["explicit"]


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(select(CourseLesson.tenant_id).distinct())
        return [r[0] for r in rows]


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Гейт досмотра для видео без ключа")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию только разбор)"
    )
    args = parser.parse_args()

    patched_lessons: list[str] = []
    explicit_lessons: list[str] = []
    affected_ids: list[UUID] = []
    total_nodes = 0
    exposed = 0

    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            lessons = list(
                (
                    await session.execute(
                        select(CourseLesson).where(
                            CourseLesson.content_format == "blocks",
                            CourseLesson.content.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            touched: list[UUID] = []
            for lesson in lessons:
                content = lesson.content or {}
                patched, added, explicit = ensure_require_full_watch(content)
                if explicit:
                    explicit_lessons.append(f"{lesson.title} ({explicit})")
                if not added:
                    continue
                # Валидируем ИТОГ: ноды после патча обязаны проходить тот же
                # whitelist, что и всё, что приходит из редактора.
                validate_lesson_content(patched)
                total_nodes += added
                patched_lessons.append(f"{lesson.title} ({added})")
                touched.append(lesson.id)
                if args.apply:
                    lesson.content = patched
                    audit.record(
                        session,
                        tenant_id=tenant_id,
                        actor_id=None,
                        action=AUDIT_ACTION,
                        object_type="course_lesson",
                        object_id=lesson.id,
                        object_label=lesson.title,
                        diff={"videos": added},
                    )

            if touched:
                affected_ids.extend(touched)
                # Сколько незавершённых прогрессов попадёт под новый гейт:
                # завершённые не перезапираются (гейты проверяются только до
                # `completed`), а вот начатые — да.
                exposed += len(
                    (
                        await session.execute(
                            select(LessonProgress.profile_id).where(
                                LessonProgress.lesson_id.in_(touched),
                                LessonProgress.status != "completed",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            if args.apply:
                await session.commit()
            else:
                await session.rollback()

    log.info(
        "backfill_require_full_watch.finished",
        applied=args.apply,
        lessons_patched=len(patched_lessons),
        video_nodes=total_nodes,
        lessons_with_explicit_false=len(explicit_lessons),
        progress_rows_now_gated=exposed,
    )
    for title in patched_lessons:
        log.info("lesson.patched", lesson=title)
    for title in explicit_lessons:
        # Явный false — возможное решение автора; трогать его нельзя.
        log.info("lesson.explicit_false_left_alone", lesson=title)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
