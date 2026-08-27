"""One-shot: разнести проект по меткам в отдельные проекты той же папки.

Зачем. В WEEEK внутри одного проекта жило несколько параллельных досок; импорт
сложил их в секции, а миграция 0047 — в метки. Для «Подбора линейного
персонала» метка это РЕКРУТЁР, и по смыслу это разные потоки работы, а не
классификация внутри одного: у каждого своя воронка, свои сроки, своя нагрузка.
Метка такое не выражает — выражает проект.

Что делает: на каждую метку исходного проекта заводит проект в той же папке,
копирует туда колонки доски и участников (роль в роль) и переносит задачи с
этой меткой. Задачи БЕЗ меток остаются в исходном проекте нетронутыми — вместе
со своими номерами.

ЦЕНА, ПРИНЯТАЯ ОСОЗНАННО: `tasks.project_id` доменно иммутабелен, а номер
«KEY-42» уникален внутри проекта (`uq_tasks_project_seq`). Перенесённая задача
обязана получить НОВЫЙ номер — значит ссылки вида «PLP-118» в комментариях и в
переписке перестанут указывать на неё. Нумеруем по возрастанию старого `seq`,
чтобы хронология внутри нового проекта совпала с прежней.

Семьи не рвём: подзадача уезжает за родителем, даже если метки у них разные
(на проде таких пар две). Иначе `parent_task_id` смотрел бы в чужой проект —
БД это стерпит, а карточка нет.

Не трогаем: комментарии, вложения, наблюдателей, исполнителей и ленту — они
привязаны к задаче и едут с ней; `position`, `done`, `completed_at` и колонку
(по имени) сохраняем как есть.

    .venv/bin/python -m app.jobs.split_project_by_labels --key PLP --prefix Подбор
    .venv/bin/python -m app.jobs.split_project_by_labels --key PLP --prefix Подбор --apply
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select

from app import log as log_config
from app.db import bypass_session_factory, tenant_scoped_session
from app.models.project import Project, ProjectMember
from app.models.stage import ProjectStage
from app.models.task import Task, TaskLabel, TaskLabelAssignment
from app.services.project_key import generate_unique_key

log = structlog.get_logger("jobs.split_project_by_labels")


@dataclass
class Group:
    """Будущий проект: метка и задачи, которые в него уедут."""

    label_id: UUID
    label_name: str
    task_ids: list[UUID] = field(default_factory=list)


async def _find_source(key: str) -> tuple[UUID, UUID] | None:
    """(tenant_id, project_id) по ключу проекта — вне tenant-контекста."""
    async with bypass_session_factory()() as scan:
        row = (
            await scan.execute(
                select(Project.tenant_id, Project.id).where(Project.key == key)
            )
        ).all()
    if not row:
        return None
    if len(row) > 1:
        raise RuntimeError(f"ключ {key!r} встречается в нескольких тенантах")
    return row[0][0], row[0][1]


async def _build_groups(session, project_id: UUID) -> list[Group]:
    """Метки проекта и задачи под каждой — с учётом семей.

    Адрес задачи определяет её собственная метка, а у подзадачи — метка
    РОДИТЕЛЯ: разорванная семья означала бы `parent_task_id` в чужой проект.
    """
    labels = (
        (
            await session.execute(
                select(TaskLabel)
                .where(TaskLabel.project_id == project_id)
                .order_by(TaskLabel.name)
            )
        )
        .scalars()
        .all()
    )
    groups = {label.id: Group(label_id=label.id, label_name=label.name) for label in labels}

    tasks = (
        await session.execute(
            select(Task.id, Task.seq, Task.parent_task_id).where(
                Task.project_id == project_id
            )
        )
    ).all()
    assignments = (
        await session.execute(
            select(TaskLabelAssignment.task_id, TaskLabelAssignment.label_id).where(
                TaskLabelAssignment.label_id.in_(list(groups))
            )
        )
    ).all()
    label_of = dict(assignments)

    seq_of = {task_id: seq for task_id, seq, _ in tasks}
    for task_id, _seq, parent_id in tasks:
        # Родитель — единственный источник адреса для подзадачи; свою метку
        # она при этом сохраняет (метки чистим ниже разом по перенесённым).
        anchor = parent_id if parent_id in seq_of else task_id
        label_id = label_of.get(anchor)
        if label_id is not None:
            groups[label_id].task_ids.append(task_id)

    for group in groups.values():
        # Новые номера идут по возрастанию старых: внутри проекта порядок
        # создания задач обязан сохраниться, иначе «первая» станет случайной.
        group.task_ids.sort(key=lambda task_id: seq_of[task_id])
    return list(groups.values())


async def _create_target(session, *, source: Project, group: Group, prefix: str) -> Project:
    """Проект-приёмник с колонками и участниками исходного.

    Намеренно НЕ `services/projects.py::create_project_record`: он заводит
    четыре колонки по умолчанию, а нам нужны колонки исходного проекта —
    иначе задачи некуда положить по имени, и пришлось бы удалять только что
    созданное.
    """
    name = f"{prefix} — {group.label_name}"
    project = Project(
        id=uuid4(),
        tenant_id=source.tenant_id,
        key=await generate_unique_key(session, name=name, tenant_id=source.tenant_id),
        name=name,
        description=source.description,
        folder_id=source.folder_id,
        created_by=source.created_by,
    )
    session.add(project)
    await session.flush()

    stages = (
        (
            await session.execute(
                select(ProjectStage)
                .where(ProjectStage.project_id == source.id)
                .order_by(ProjectStage.position)
            )
        )
        .scalars()
        .all()
    )
    for stage in stages:
        session.add(
            ProjectStage(
                id=uuid4(),
                tenant_id=source.tenant_id,
                project_id=project.id,
                name=stage.name,
                position=stage.position,
            )
        )

    members = (
        (
            await session.execute(
                select(ProjectMember).where(ProjectMember.project_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    for member in members:
        session.add(
            ProjectMember(
                id=uuid4(),
                tenant_id=source.tenant_id,
                project_id=project.id,
                employee_id=member.employee_id,
                role=member.role,
                added_by=member.added_by,
            )
        )
    await session.flush()
    return project


async def _move_tasks(session, *, source_id: UUID, target: Project, group: Group) -> None:
    """Перенос с перенумерацией и пересадкой на одноимённую колонку."""
    stage_map: dict[UUID, UUID] = {}
    src_stages = (
        await session.execute(
            select(ProjectStage.id, ProjectStage.name).where(
                ProjectStage.project_id == source_id
            )
        )
    ).all()
    dst_stages = dict(
        (
            await session.execute(
                select(ProjectStage.name, ProjectStage.id).where(
                    ProjectStage.project_id == target.id
                )
            )
        ).all()
    )
    for stage_id, stage_name in src_stages:
        stage_map[stage_id] = dst_stages[stage_name]

    for number, task_id in enumerate(group.task_ids, start=1):
        task = await session.get(Task, task_id)
        assert task is not None
        task.project_id = target.id
        task.seq = number
        # `stage_id IS NULL` — «задача без статуса» (0046), законное состояние:
        # переносить нечего, и подставлять первую колонку нельзя.
        if task.stage_id is not None:
            task.stage_id = stage_map[task.stage_id]
    target.next_task_seq = len(group.task_ids) + 1
    await session.flush()


async def _clear_labels(session, groups: list[Group]) -> None:
    """Снять метку с перенесённых задач и убрать саму метку из исходного.

    Метка своё отработала: рекрутёра теперь называет проект. Оставить
    назначение нельзя — оно указывало бы на метку ЧУЖОГО проекта, и в карточке
    это чужой чип. Пустую метку в исходном проекте тоже убираем: фильтр по ней
    возвращал бы ноль задач всегда.
    """
    moved_ids = [task_id for group in groups for task_id in group.task_ids]
    if moved_ids:
        await session.execute(
            delete(TaskLabelAssignment).where(TaskLabelAssignment.task_id.in_(moved_ids))
        )
        await session.flush()
    # Только опустевшие: если метку успели навесить на задачу, оставшуюся в
    # исходном проекте, она там и нужна.
    empty = (
        await session.execute(
            select(TaskLabel.id)
            .where(TaskLabel.id.in_([g.label_id for g in groups]))
            .where(
                ~select(TaskLabelAssignment.task_id)
                .where(TaskLabelAssignment.label_id == TaskLabel.id)
                .exists()
            )
        )
    ).scalars().all()
    if empty:
        await session.execute(delete(TaskLabel).where(TaskLabel.id.in_(list(empty))))
        await session.flush()


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Проект по меткам → отдельные проекты")
    parser.add_argument("--key", required=True, help="ключ исходного проекта, напр. PLP")
    parser.add_argument(
        "--prefix", help="начало имени новых проектов (по умолчанию — имя исходного)"
    )
    parser.add_argument("--apply", action="store_true", help="записать (по умолчанию разбор)")
    args = parser.parse_args()

    found = await _find_source(args.key)
    if found is None:
        log.error("split.source_not_found", key=args.key)
        return 1
    tenant_id, project_id = found

    async with tenant_scoped_session(tenant_id) as session:
        source = await session.get(Project, project_id)
        assert source is not None
        prefix = args.prefix or source.name
        groups = await _build_groups(session, project_id)
        stayed = (
            await session.execute(
                select(Task.id).where(Task.project_id == project_id)
            )
        ).all()
        moving = sum(len(g.task_ids) for g in groups)

        log.info(
            "split.plan",
            source=source.name,
            source_key=source.key,
            tasks_total=len(stayed),
            tasks_moving=moving,
            tasks_staying=len(stayed) - moving,
            groups={g.label_name: len(g.task_ids) for g in groups},
        )

        if not args.apply:
            log.info("split.dry_run", hint="повторите с --apply, чтобы записать")
            return 0

        for group in groups:
            target = await _create_target(
                session, source=source, group=group, prefix=prefix
            )
            await _move_tasks(
                session, source_id=project_id, target=target, group=group
            )
            log.info(
                "split.moved",
                label=group.label_name,
                project=target.name,
                key=target.key,
                tasks=len(group.task_ids),
            )

        await _clear_labels(session, groups)
        await session.commit()

    log.info("split.done", groups=len(groups), tasks=moving)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
