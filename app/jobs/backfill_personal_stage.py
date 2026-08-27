"""One-shot: снять статус с личных задач, заведённых до этой правки.

На живом пути задача в личном пространстве заводится БЕЗ статуса
(`tasks.create_task_record`): личное — список дел, а не доска. Но до правки
`require_stage` (ныне `default_stage_for`) клал такую задачу в ПЕРВУЮ колонку, и все уже
существующие личные задачи (в первую очередь «Изучите инструкцию по работе в
Hub») молча осели в «К выполнению» — колонке, которую владелец никогда не
выбирал.

Осторожность: снимаем статус ТОЛЬКО у задач, которых колонки никогда не
касались руками, — то есть без единой записи `stage_changed` в ленте. Если
человек сам передвинул свою личную задачу по доске, его выбор остаётся.

`task_activity` не трогаем: «сняли статус» здесь — исправление дефекта записи,
а не действие пользователя, и строка «убрал статус» в истории задачи врала бы
про автора.

    .venv/bin/python -m app.jobs.backfill_personal_stage            # разбор
    .venv/bin/python -m app.jobs.backfill_personal_stage --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog
from sqlalchemy import exists, func, select, update

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.project import Project
from app.models.stage import ProjectStage
from app.models.task import Task, TaskActivity

log = structlog.get_logger("jobs.backfill_personal_stage")


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(
            select(Project.tenant_id)
            .where(Project.personal_owner_id.is_not(None))
            .distinct()
        )
        return [r[0] for r in rows]


def _touched_by_hand() -> object:
    """У задачи есть запись о смене колонки — значит владелец её ставил сам."""
    return exists().where(
        TaskActivity.task_id == Task.id, TaskActivity.kind == "stage_changed"
    )


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Прочерк у личных задач")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию только разбор)"
    )
    args = parser.parse_args()

    total = 0
    kept = 0
    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            personal = select(Project.id).where(Project.personal_owner_id.is_not(None))

            rows = (
                await session.execute(
                    select(Task.id, Task.title, ProjectStage.name)
                    .join(ProjectStage, ProjectStage.id == Task.stage_id)
                    .where(Task.project_id.in_(personal), ~_touched_by_hand())
                )
            ).all()
            kept += (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(
                        Task.project_id.in_(personal),
                        Task.stage_id.is_not(None),
                        _touched_by_hand(),
                    )
                )
            ).scalar_one()

            for _task_id, title, stage_name in rows:
                total += 1
                log.info(
                    "personal_stage.clear" if args.apply else "personal_stage.pending",
                    title=title,
                    stage=stage_name,
                )
            if args.apply and rows:
                await session.execute(
                    update(Task)
                    .where(Task.id.in_([r[0] for r in rows]))
                    .values(stage_id=None)
                )
                await session.commit()

    log.info(
        "backfill.personal_stage.summary",
        applied=args.apply,
        cleared=total,
        kept_manual=kept,
    )
    if not args.apply:
        log.info("backfill.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
