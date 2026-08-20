"""Этапы проекта (редизайн, волна 2): дефолтные этапы, зеркало status,
legacy-вход status, инвариант «≥1 этап на системный статус», перенос при
удалении, позиции, RLS-изоляция.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.stages import create_stage, delete_stage, list_project_stages, update_stage
from app.api.tasks import create_task, get_task, update_task
from app.schemas.project import ProjectCreate
from app.schemas.stage import StageCreate, StageUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _by_status(db: AsyncSession, project_id: uuid.UUID, owner):
    stages = await list_project_stages(project_id, principal=owner, db=db)
    return {s.system_status: s for s in stages}


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Stages {slug}"), owner, db)
    return owner, project


async def test_new_project_gets_four_default_stages(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st1")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.system_status for s in stages] == ["todo", "in_progress", "in_review", "done"]
    assert [s.position for s in stages] == [0, 1, 2, 3]
    assert stages[3].name == "Готово"
    assert all(s.task_count == 0 for s in stages)


async def test_create_task_legacy_status_lands_in_first_stage_of_status(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "st2")
    stages = await _by_status(db, project.id, owner)
    task = await create_task(
        project.id, TaskCreate(title="Legacy", status="in_review"), owner, db
    )
    assert task.stage_id == stages["in_review"].id
    assert task.status == "in_review"
    # stage_id без status — зеркало проставляется из этапа
    t2 = await create_task(
        project.id, TaskCreate(title="По этапу", stage_id=stages["done"].id), owner, db
    )
    assert t2.status == "done"
    assert t2.completed_at is not None


async def test_update_stage_id_mirrors_status_and_counts(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st3")
    stages = await _by_status(db, project.id, owner)
    task = await create_task(project.id, TaskCreate(title="Переезд"), owner, db)
    moved = await update_task(task.id, TaskUpdate(stage_id=stages["done"].id), owner, db)
    assert moved.status == "done"
    assert moved.stage_id == stages["done"].id
    assert moved.completed_at is not None
    # legacy PATCH {status} — в первый этап статуса
    back = await update_task(task.id, TaskUpdate(status="todo"), owner, db)
    assert back.stage_id == stages["todo"].id
    assert back.completed_at is None
    # оба и не согласованы → 422
    with pytest.raises(HTTPException) as exc:
        await update_task(
            task.id, TaskUpdate(stage_id=stages["done"].id, status="todo"), owner, db
        )
    assert exc.value.status_code == 422
    counts = {k: v.task_count for k, v in (await _by_status(db, project.id, owner)).items()}
    assert counts["todo"] == 1 and counts["done"] == 0


async def test_custom_stage_same_status_is_a_real_move(db: AsyncSession, tenant_id: uuid.UUID):
    """«В работе» → «Проверка ТУ» (оба in_review/in_progress): этап меняется,
    статус-зеркало — по этапу."""
    owner, project = await _seed(db, tenant_id, "st4")
    tu = await create_stage(
        project.id, StageCreate(name="Проверка ТУ", system_status="in_review"), owner, db
    )
    stages = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.position for s in stages] == [0, 1, 2, 3, 4]
    task = await create_task(project.id, TaskCreate(title="На ТУ"), owner, db)
    moved = await update_task(task.id, TaskUpdate(stage_id=tu.id), owner, db)
    assert moved.stage_id == tu.id and moved.status == "in_review"
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id == tu.id


async def test_cannot_delete_last_stage_of_status_and_move_on_delete(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "st5")
    stages = await _by_status(db, project.id, owner)
    with pytest.raises(HTTPException) as exc:
        await delete_stage(stages["done"].id, move_to=None, principal=owner, db=db)
    assert exc.value.status_code == 409

    extra = await create_stage(
        project.id, StageCreate(name="Готово-2", system_status="done"), owner, db
    )
    task = await create_task(project.id, TaskCreate(title="В доп", stage_id=extra.id), owner, db)
    with pytest.raises(HTTPException) as exc:
        await delete_stage(extra.id, move_to=None, principal=owner, db=db)
    assert exc.value.status_code == 409, "с задачами нужен move_to"
    await delete_stage(extra.id, move_to=stages["todo"].id, principal=owner, db=db)
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id == stages["todo"].id
    assert fresh.status == "todo" and fresh.completed_at is None
    left = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.position for s in left] == [0, 1, 2, 3]


async def test_change_system_status_rewrites_mirror(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st6")
    extra = await create_stage(
        project.id, StageCreate(name="Бэклог", system_status="todo"), owner, db
    )
    task = await create_task(
        project.id, TaskCreate(title="В бэклоге", stage_id=extra.id), owner, db
    )
    assert task.status == "todo"
    await update_stage(extra.id, StageUpdate(system_status="in_progress"), owner, db)
    fresh = await get_task(task.id, owner, db)
    assert fresh.status == "in_progress"
    # переименование и перестановка
    renamed = await update_stage(extra.id, StageUpdate(name="Разбор", position=0), owner, db)
    assert renamed.name == "Разбор" and renamed.position == 0
    stages = await list_project_stages(project.id, principal=owner, db=db)
    assert stages[0].id == extra.id
    assert [s.position for s in stages] == [0, 1, 2, 3, 4]


async def test_stats_stage_breakdown(db: AsyncSession, tenant_id: uuid.UUID):
    from app.api.stats import get_stats

    owner, project = await _seed(db, tenant_id, "st7")
    stages = await _by_status(db, project.id, owner)
    await create_task(project.id, TaskCreate(title="A"), owner, db)
    await create_task(project.id, TaskCreate(title="B", stage_id=stages["done"].id), owner, db)
    stats = await get_stats(project.id, principal=owner, db=db)
    assert stats.stage_breakdown[str(stages["todo"].id)] == 1
    assert stats.stage_breakdown[str(stages["done"].id)] == 1
    assert stats.status_breakdown["done"] == 1
