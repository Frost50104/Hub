"""Разделение проекта по меткам — одноразовая джоба, но на 1 272 живых задачи.

Проверяем ровно то, что нельзя откатить кнопкой: номера, семьи и колонки.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.labels import assign_label, create_label
from app.api.projects import create_project
from app.api.stages import list_project_stages
from app.api.tasks import create_task
from app.jobs.split_project_by_labels import (
    _build_groups,
    _clear_labels,
    _create_target,
    _move_tasks,
)
from app.models.project import Project, ProjectMember
from app.models.stage import ProjectStage
from app.models.task import Task, TaskLabel, TaskLabelAssignment
from app.schemas.label import LabelCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """Проект с двумя метками: «Алена» на двух задачах, «Оля» на одной."""
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Подбор {slug}"), owner, db)
    # Колонки — явным сидом: проект их больше не создаёт, а джоба копирует
    # колонки в проекты-приёмники ПО ИМЕНИ, и копировать должно быть что.
    await seed_stages(db, project.id, owner)
    stages = await list_project_stages(project.id, principal=owner, db=db)

    alena = await create_label(project.id, LabelCreate(name="Алена"), owner, db)
    olya = await create_label(project.id, LabelCreate(name="Оля"), owner, db)

    async def task(title: str, *, stage_id=None, parent=None):
        return await create_task(
            project.id,
            TaskCreate(title=title, stage_id=stage_id, parent_task_id=parent),
            owner,
            db,
        )

    t1 = await task("Алена: первая", stage_id=stages[1].id)
    t2 = await task("Оля: первая", stage_id=stages[2].id)
    t3 = await task("Алена: вторая")
    orphan = await task("Ничья")
    # Подзадача под задачей Алены, но с меткой Оли — семью рвать нельзя.
    child = await task("Подзадача Алены", parent=t1.id)

    for task_id, label_id in (
        (t1.id, alena.id),
        (t3.id, alena.id),
        (t2.id, olya.id),
        (child.id, olya.id),
    ):
        await assign_label(task_id, label_id, owner, db)
    await db.commit()
    return {
        "owner": owner, "project": project, "stages": stages,
        "t1": t1, "t2": t2, "t3": t3, "orphan": orphan, "child": child,
    }


async def _run(db: AsyncSession, seed: dict) -> dict[str, Project]:
    source = await db.get(Project, seed["project"].id)
    assert source is not None
    out: dict[str, Project] = {}
    for group in await _build_groups(db, source.id):
        target = await _create_target(db, source=source, group=group, prefix="Подбор")
        await _move_tasks(db, source_id=source.id, target=target, group=group)
        out[group.label_name] = target
    await db.commit()
    return out


async def test_tasks_split_by_label_and_renumbered(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    targets = await _run(db, seed)

    assert set(targets) == {"Алена", "Оля"}
    assert targets["Алена"].name == "Подбор — Алена"

    t1 = await db.get(Task, seed["t1"].id)
    t3 = await db.get(Task, seed["t3"].id)
    t2 = await db.get(Task, seed["t2"].id)
    orphan = await db.get(Task, seed["orphan"].id)
    assert t1.project_id == targets["Алена"].id
    assert t3.project_id == targets["Алена"].id
    assert t2.project_id == targets["Оля"].id
    # Задача без метки остаётся в исходном проекте — вместе со своим номером.
    assert orphan.project_id == seed["project"].id
    assert orphan.seq == seed["orphan"].seq

    # Нумерация с единицы и в прежнем хронологическом порядке.
    assert (t1.seq, t3.seq) == (1, 2)
    assert t2.seq == 1
    # Три задачи у «Алены» — своя, вторая и уехавшая за родителем подзадача.
    assert targets["Алена"].next_task_seq == 4


async def test_subtask_follows_parent_not_its_own_label(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    targets = await _run(db, seed)

    child = await db.get(Task, seed["child"].id)
    parent = await db.get(Task, seed["t1"].id)
    # У подзадачи метка «Оля», у родителя «Алена» — едет за родителем, иначе
    # parent_task_id смотрел бы в чужой проект.
    assert child.project_id == parent.project_id == targets["Алена"].id
    assert child.seq != parent.seq


async def test_columns_copied_by_name_and_null_stays_null(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    src_names = [s.name for s in seed["stages"]]
    targets = await _run(db, seed)

    rows = (
        await db.execute(
            select(ProjectStage.name)
            .where(ProjectStage.project_id == targets["Алена"].id)
            .order_by(ProjectStage.position)
        )
    ).scalars().all()
    assert list(rows) == src_names

    t1 = await db.get(Task, seed["t1"].id)
    new_stage = await db.get(ProjectStage, t1.stage_id)
    # Колонка та же по имени, но уже своя — чужую бы не пустил список доски.
    assert new_stage.name == seed["stages"][1].name
    assert new_stage.project_id == targets["Алена"].id

    t3 = await db.get(Task, seed["t3"].id)
    assert t3.stage_id is not None  # create_task кладёт в первую колонку


async def test_members_copied_role_for_role(db: AsyncSession, tenant_id: uuid.UUID):
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    targets = await _run(db, seed)

    src = (
        await db.execute(
            select(ProjectMember.employee_id, ProjectMember.role).where(
                ProjectMember.project_id == seed["project"].id
            )
        )
    ).all()
    dst = (
        await db.execute(
            select(ProjectMember.employee_id, ProjectMember.role).where(
                ProjectMember.project_id == targets["Оля"].id
            )
        )
    ).all()
    assert sorted(src) == sorted(dst)


async def test_dry_run_changes_nothing(db: AsyncSession, tenant_id: uuid.UUID):
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    before = (
        await db.execute(
            select(Task.id, Task.seq, Task.project_id).where(
                Task.project_id == seed["project"].id
            )
        )
    ).all()

    groups = await _build_groups(db, seed["project"].id)

    assert {g.label_name: len(g.task_ids) for g in groups} == {"Алена": 3, "Оля": 1}
    after = (
        await db.execute(
            select(Task.id, Task.seq, Task.project_id).where(
                Task.project_id == seed["project"].id
            )
        )
    ).all()
    assert sorted(before) == sorted(after)


async def test_labels_of_moved_tasks_are_cleared(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Чип рекрутёра снимается — его роль взял на себя сам проект."""
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    source = await db.get(Project, seed["project"].id)
    groups = await _build_groups(db, source.id)
    for group in groups:
        target = await _create_target(db, source=source, group=group, prefix="Подбор")
        await _move_tasks(db, source_id=source.id, target=target, group=group)
    await _clear_labels(db, groups)
    await db.commit()

    seeded = [seed[k].id for k in ("t1", "t2", "t3", "orphan", "child")]
    assigned = (
        await db.execute(
            select(TaskLabelAssignment.task_id).where(
                TaskLabelAssignment.task_id.in_(seeded)
            )
        )
    ).scalars().all()
    assert list(assigned) == []
    # Метка исходного проекта опустела и снята — иначе фильтр по ней всегда
    # давал бы ноль.
    left = (
        await db.execute(
            select(TaskLabel.name).where(TaskLabel.project_id == source.id)
        )
    ).scalars().all()
    assert list(left) == []


async def test_label_still_used_by_a_staying_task_survives(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Метку, оставшуюся на невыехавшей задаче, чистка не трогает."""
    seed = await _seed(db, tenant_id, f"sp{uuid.uuid4().hex[:6]}")
    source = await db.get(Project, seed["project"].id)
    groups = await _build_groups(db, source.id)
    alena = next(g for g in groups if g.label_name == "Алена")
    # «Забываем» перенести задачу, помеченную именно «Аленой». Последняя в
    # группе не подошла бы: это подзадача с меткой «Оля», уехавшая за
    # родителем.
    alena.task_ids.remove(seed["t3"].id)

    for group in groups:
        target = await _create_target(db, source=source, group=group, prefix="Подбор")
        await _move_tasks(db, source_id=source.id, target=target, group=group)
    await _clear_labels(db, groups)
    await db.commit()

    left = (
        await db.execute(
            select(TaskLabel.name).where(TaskLabel.project_id == source.id)
        )
    ).scalars().all()
    assert list(left) == ["Алена"]
