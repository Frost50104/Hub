"""One-shot: сделать владельца исполнителем его личных задач.

На живом пути задача в личном пространстве получает владельца в исполнители
сразу (`tasks.create_task_record`): задача «на себя», других исполнителей там
не бывает. Но заведённые до этой правки остались ничьими — пустой стек
аватаров в строке и промах фильтра «Исполнитель».

Трогаем ТОЛЬКО задачи вообще без исполнителей: если в чьём-то личном проекте
исполнитель уже есть (общая задача из `_shared_personal`-сценария), набор
чужой и решать за него нечего.

Уведомлений нет по построению: `apply_assignee_side_effects` пропускает
само-назначение (`employee_id == actor_id`), а `record=False` не плодит
записей «назначил» в ленте — история задачи остаётся с одной строкой «создал».

    .venv/bin/python -m app.jobs.backfill_personal_assignee            # разбор
    .venv/bin/python -m app.jobs.backfill_personal_assignee --apply    # запись
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog
from sqlalchemy import exists, func, select

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.project import Project
from app.models.task import Task, TaskAssignee
from app.services.task_assignees import (
    apply_assignee_side_effects,
    set_task_assignees,
)

log = structlog.get_logger("jobs.backfill_personal_assignee")


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(
            select(Project.tenant_id)
            .where(Project.personal_owner_id.is_not(None))
            .distinct()
        )
        return [r[0] for r in rows]


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Владелец — исполнитель личных задач")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию только разбор)"
    )
    args = parser.parse_args()

    assigned = 0
    kept = 0
    for tenant_id in await _tenant_ids():
        async with tenant_scoped_session(tenant_id) as session:
            has_assignee = exists().where(TaskAssignee.task_id == Task.id)
            rows = (
                await session.execute(
                    select(Task, Project.personal_owner_id)
                    .join(Project, Project.id == Task.project_id)
                    .where(Project.personal_owner_id.is_not(None), ~has_assignee)
                )
            ).all()
            kept += (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .join(Project, Project.id == Task.project_id)
                    .where(Project.personal_owner_id.is_not(None), has_assignee)
                )
            ).scalar_one()

            for task, owner_id in rows:
                assigned += 1
                log.info(
                    "personal_assignee.set" if args.apply else "personal_assignee.pending",
                    title=task.title,
                )
                if not args.apply:
                    continue
                diff = await set_task_assignees(
                    session, task=task, employee_ids=[owner_id], actor_id=owner_id
                )
                await apply_assignee_side_effects(
                    session,
                    task=task,
                    diff=diff,
                    actor_id=owner_id,
                    actor_name="",
                    notify=False,
                    record=False,
                )
            if args.apply and rows:
                await session.commit()

    log.info(
        "backfill.personal_assignee.summary",
        applied=args.apply,
        assigned=assigned,
        already_had=kept,
    )
    if not args.apply:
        log.info("backfill.dry_run", hint="повторите с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
