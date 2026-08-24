"""Кто может менять статус задачи.

Назначение исполнителем выдаёт viewer-членство (`ensure_project_member`), а
`PATCH /tasks/{id}` требует owner/editor — до этого правила исполнитель не мог
отметить собственную задачу выполненной. Теперь может, но ТОЛЬКО статус и этап.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.tasks import create_task, get_task, list_tasks, update_task
from app.models.project import ProjectMember
from app.models.stage import ProjectStage
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _setup(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """(владелец, исполнитель-наблюдатель, сторонний наблюдатель, проект, задача)."""
    owner = make_principal(tenant_id, email=f"{slug}-o@t.ru", tenant_slug=slug)
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)

    assignee = make_principal(tenant_id, email=f"{slug}-a@t.ru", tenant_slug=slug)
    bystander = make_principal(tenant_id, email=f"{slug}-b@t.ru", tenant_slug=slug)
    for p in (assignee, bystander):
        await _register(db, p)
    # Сторонний — наблюдатель без назначения.
    db.add(
        ProjectMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            project_id=project.id,
            employee_id=bystander.employee_id,
            role="viewer",
            added_by=owner.employee_id,
        )
    )
    task = await create_task(
        project.id,
        TaskCreate(title="Забрать акты", assignee_ids=[assignee.employee_id]),
        owner,
        db,
    )
    await db.commit()
    return owner, assignee, bystander, project, task


async def _list(db: AsyncSession, project_id: uuid.UUID, principal):
    return await list_tasks(
        project_id,
        include_archived=False,
        done=None,
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
        stage_id=None,
    )


async def test_assignee_is_only_viewer(db, tenant_id):
    """Контекст задачи: назначение даёт именно viewer, а не editor."""
    _owner, assignee, _bystander, project, _task = await _setup(db, tenant_id, "tp-role")
    role = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.employee_id == assignee.employee_id,
            )
        )
    ).scalar_one()
    assert role == "viewer"


async def test_assignee_closes_own_task(db, tenant_id):
    _owner, assignee, _bystander, _project, task = await _setup(db, tenant_id, "tp-done")
    before = task.stage_id
    updated = await update_task(task.id, TaskUpdate(done=True), assignee, db)
    assert updated.done is True
    assert updated.completed_at is not None
    # Галочка не двигает карточку по доске (0044).
    assert updated.stage_id == before


async def test_assignee_moves_own_task_by_stage(db, tenant_id):
    _owner, assignee, _bystander, project, task = await _setup(db, tenant_id, "tp-stage")
    target = (
        await db.execute(
            select(ProjectStage)
            .where(ProjectStage.project_id == project.id, ProjectStage.position == 1)
        )
    ).scalars().first()
    updated = await update_task(task.id, TaskUpdate(stage_id=target.id), assignee, db)
    assert updated.stage_id == target.id
    # Перенос не закрывает и не открывает задачу.
    assert updated.done is False


@pytest.mark.parametrize(
    "patch",
    [
        pytest.param({"title": "Переименовал"}, id="title"),
        pytest.param({"priority": "urgent"}, id="priority"),
        pytest.param({"done": True, "priority": "urgent"}, id="done+priority"),
        pytest.param({"position": 42}, id="position"),
    ],
)
async def test_assignee_cannot_change_anything_else(db, tenant_id, patch):
    """Смешанный патч и любое поле сверх «выполнена»/колонки — 403.

    `{stage_id, position}` — форма, которую шлёт drag-n-drop доски: правило
    сознательно её не пускает, порядок остаётся редакторским.
    """
    _owner, assignee, _bystander, _project, task = await _setup(
        db, tenant_id, f"tp-no-{abs(hash(str(patch))) % 9999}"
    )
    with pytest.raises(HTTPException) as exc:
        await update_task(task.id, TaskUpdate(**patch), assignee, db)
    assert exc.value.status_code == 403


async def test_board_drag_shape_rejected_for_assignee(db, tenant_id):
    _owner, assignee, _bystander, project, task = await _setup(db, tenant_id, "tp-drag")
    target = (
        await db.execute(
            select(ProjectStage).where(
                ProjectStage.project_id == project.id, ProjectStage.position == 2
            )
        )
    ).scalars().first()
    with pytest.raises(HTTPException) as exc:
        await update_task(
            task.id, TaskUpdate(stage_id=target.id, position=7), assignee, db
        )
    assert exc.value.status_code == 403


async def test_bystander_viewer_still_denied(db, tenant_id):
    """Главный регресс: право получил ИСПОЛНИТЕЛЬ, а не всякий наблюдатель."""
    _owner, _assignee, bystander, _project, task = await _setup(db, tenant_id, "tp-by")
    with pytest.raises(HTTPException) as exc:
        await update_task(task.id, TaskUpdate(done=True), bystander, db)
    assert exc.value.status_code == 403


async def test_can_complete_in_list_and_detail(db, tenant_id):
    owner, assignee, bystander, project, task = await _setup(db, tenant_id, "tp-flag")

    for principal, expected in ((owner, True), (assignee, True), (bystander, False)):
        rows = await _list(db, project.id, principal)
        assert [t.can_complete for t in rows] == [expected]
        assert (await get_task(task.id, principal, db)).can_complete is expected


async def test_me_tasks_leaves_flag_unknown(db, tenant_id):
    """`/me/tasks` роли не считает — поле остаётся None («не знаем»)."""
    from app.api.me_tasks import list_my_tasks

    _owner, assignee, _bystander, _project, _task = await _setup(db, tenant_id, "tp-me")
    rows = await list_my_tasks(
        done=None,
        status_=None,
        due_window=None,
        include_archived=False,
        include_personal=False,
        principal=assignee,
        db=db,
    )
    assert [t.can_complete for t in rows] == [None]


async def test_assistant_lets_assignee_complete(db, tenant_id):
    """Ассистент не должен отказывать там, где человек ставит галочку."""
    from app.services.assistant.context import ToolContext
    from app.services.assistant.tools import UpdateTaskArgs, t_update_task

    _owner, assignee, bystander, project, task = await _setup(db, tenant_id, "tp-ai")
    ctx = ToolContext(db=db, principal=assignee, profile=None)
    result = await t_update_task(
        ctx, UpdateTaskArgs(task=f"{project.key}-{task.seq}", done=True)
    )
    assert result.get("ok") is True
    assert result.get("done") is True

    # Наблюдателю без назначения — прежний отказ данными, с «кого просить».
    denied_ctx = ToolContext(db=db, principal=bystander, profile=None)
    refusal = await t_update_task(
        denied_ctx, UpdateTaskArgs(task=f"{project.key}-{task.seq}", done=False)
    )
    assert refusal["denied"] is True
    assert "наблюдател" in refusal["reason"]
    assert refusal["who_can"]

    # И даже исполнителю — если правка выходит за пределы статуса.
    beyond = await t_update_task(
        ctx, UpdateTaskArgs(task=f"{project.key}-{task.seq}", title="Переименовал")
    )
    assert beyond["denied"] is True
