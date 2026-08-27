"""One-shot: снять НАВЯЗАННЫЕ стартовые колонки у проектов, где ими не пользовались.

Зачем. До 26.08 каждый новый проект рождался с четырьмя колонками
(«К выполнению», «В работе», «На проверке», «Готово») — их никто не выбирал, но
на доске они выглядели как готовая раскладка. Теперь проект рождается без
колонок; эта джоба доводит до того же состояния уже созданные, но не начатые
проекты.

Условие удаления — ВСЁ СРАЗУ, иначе не трогаем:

1. в проекте ноль задач (любых: архивных, подзадач — считаем строки `tasks`);
2. набор колонок — РОВНО стартовая четвёрка, в стартовом порядке.

Второй пункт важнее первого: проект без задач мог быть подготовлен под работу —
кто-то переименовал колонки, добавил свои, поменял порядок. Такую раскладку
джоба обязана оставить в покое, даже если задач ещё нет.

Идемпотентна по построению: второй прогон просто не найдёт подходящих проектов.

    .venv/bin/python -m app.jobs.drop_default_stages
    .venv/bin/python -m app.jobs.drop_default_stages --apply
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select

from app import log as log_config
from app.db import bypass_session_factory
from app.models.project import Project
from app.models.stage import ProjectStage
from app.models.task import Task

log = structlog.get_logger("jobs.drop_default_stages")

# Историческая четвёрка. Живёт ЗДЕСЬ, а не в `services/stages.py`: в проде её
# больше никто не создаёт, и константа в сервисе была бы приглашением вернуть
# сид обратно.
LEGACY_DEFAULT_STAGES: tuple[str, ...] = (
    "К выполнению",
    "В работе",
    "На проверке",
    "Готово",
)


async def find_candidates(session) -> list[tuple[Project, list[ProjectStage]]]:
    """Проекты под оба условия — вместе с их колонками (кросс-тенантно)."""
    task_counts = dict(
        (
            await session.execute(
                select(Task.project_id, func.count()).group_by(Task.project_id)
            )
        ).all()
    )
    stages_by_project: dict[UUID, list[ProjectStage]] = {}
    for stage in (
        (await session.execute(select(ProjectStage).order_by(ProjectStage.position)))
        .scalars()
        .all()
    ):
        stages_by_project.setdefault(stage.project_id, []).append(stage)

    out: list[tuple[Project, list[ProjectStage]]] = []
    for project in (await session.execute(select(Project))).scalars().all():
        if task_counts.get(project.id, 0):
            continue
        stages = stages_by_project.get(project.id, [])
        if tuple(s.name for s in stages) != LEGACY_DEFAULT_STAGES:
            continue
        out.append((project, stages))
    return out


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(
        description="Снять стартовые колонки у проектов без задач"
    )
    parser.add_argument("--apply", action="store_true", help="записать (по умолчанию разбор)")
    args = parser.parse_args()

    # Кросс-тенантная работа: одна сессия с bypass_rls, как у deletion-sync.
    # Тенантов у Hub немного, а проект ищется по всем сразу.
    async with bypass_session_factory()() as session:
        candidates = await find_candidates(session)
        log.info(
            "drop_default_stages.plan",
            projects=[f"{p.key} · {p.name}" for p, _ in candidates],
            count=len(candidates),
        )
        if not candidates:
            log.info("drop_default_stages.nothing_to_do")
            return 0
        if not args.apply:
            log.info("drop_default_stages.dry_run", hint="повторите с --apply, чтобы записать")
            return 0

        for project, stages in candidates:
            await session.execute(
                delete(ProjectStage).where(
                    ProjectStage.id.in_([s.id for s in stages])
                )
            )
            log.info("drop_default_stages.cleared", key=project.key, stages=len(stages))
        await session.commit()

    log.info("drop_default_stages.done", projects=len(candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
