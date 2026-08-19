"""Счётчики строки списка задач и счётчики задач в проекте (редизайн трекера).

Строка контекста в списке обещает «2 комментария», «1 вложение» и «зависит от
задачи», шапка проекта — «N задач». Оба набора считаются батчем и НЕ через
JOIN к задаче: JOIN размножил бы строку по числу комментариев.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.comments import create_comment
from app.api.dependencies import add_dependency
from app.api.projects import create_project, get_project, list_projects
from app.api.tasks import archive_task, create_task, get_task, list_tasks
from app.schemas.comment import CommentCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _list(db: AsyncSession, project_id: uuid.UUID, principal):
    """list_tasks с явными Query-дефолтами (напрямую FastAPI их не резолвит)."""
    return await list_tasks(
        project_id,
        include_archived=False,
        status_=None,
        assignee_id=None,
        section_id=None,
        priority=None,
        label=None,
        due_from=None,
        due_to=None,
        sort="position",
        order="asc",
        principal=principal,
        db=db,
    )


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Counts {slug}"), owner, db)
    return owner, project


async def test_row_counts_are_per_task(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "cnt1")
    loud = await create_task(project.id, TaskCreate(title="С обсуждением"), owner, db)
    await create_task(project.id, TaskCreate(title="Без всего"), owner, db)
    blocker = await create_task(project.id, TaskCreate(title="Блокирует"), owner, db)

    await create_comment(loud.id, CommentCreate(body="Первый"), owner, db)
    await create_comment(loud.id, CommentCreate(body="Второй"), owner, db)
    await add_dependency(loud.id, blocker.id, owner, db)

    rows = {t.title: t for t in await _list(db, project.id, owner)}

    assert rows["С обсуждением"].comment_count == 2
    assert rows["С обсуждением"].blocker_count == 1
    assert rows["С обсуждением"].attachment_count == 0

    # Ноль — это знание, а не «не знаем»: чип не рисуется, но поле заполнено.
    assert rows["Без всего"].comment_count == 0
    assert rows["Без всего"].blocker_count == 0

    # Зависимость висит на successor'е, а не на предшественнике: строка списка
    # сообщает «зависит от задачи», а не «её ждут».
    assert rows["Блокирует"].blocker_count == 0


async def test_single_task_handle_leaves_counts_unknown(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Одиночная ручка не платит за три лишних запроса и отдаёт None."""
    owner, project = await _seed(db, tenant_id, "cnt2")
    task = await create_task(project.id, TaskCreate(title="Одна"), owner, db)
    await create_comment(task.id, CommentCreate(body="Есть"), owner, db)

    one = await get_task(task.id, owner, db)
    assert one.comment_count is None
    assert one.attachment_count is None
    assert one.blocker_count is None


async def test_project_counts_skip_subtasks_and_archived(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "cnt3")
    parent = await create_task(project.id, TaskCreate(title="Родитель"), owner, db)
    await create_task(
        project.id,
        TaskCreate(title="Подзадача", parent_task_id=parent.id),
        owner,
        db,
    )
    await create_task(project.id, TaskCreate(title="Готовая", status="done"), owner, db)
    trash = await create_task(project.id, TaskCreate(title="В архив"), owner, db)
    await archive_task(trash.id, owner, db)

    fetched = await get_project(project.id, owner, db)
    # Родитель + готовая. Подзадача живёт в карточке родителя, архивная не в счёт.
    assert fetched.task_count == 2
    assert fetched.done_count == 1

    listed = {p.id: p for p in await list_projects(False, owner, db)}
    assert listed[project.id].task_count == 2
    assert listed[project.id].done_count == 1


async def test_project_counts_do_not_leak_across_tenants(db: AsyncSession):
    """RLS: счётчик считает только свой тенант."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    owner_a, project_a = await _seed(db, tenant_a, "cnta")
    await create_task(project_a.id, TaskCreate(title="Чужая"), owner_a, db)

    owner_b, project_b = await _seed(db, tenant_b, "cntb")
    fetched = await get_project(project_b.id, owner_b, db)
    assert fetched.task_count == 0
