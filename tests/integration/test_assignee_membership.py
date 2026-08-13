"""Авто-членство при назначении исполнителя (ensure_project_member + 0033).

Контракт: назначение assignee создаёт viewer-строку в project_members
(идемпотентно, без даунгрейда существующих ролей) — deep-link из «Все
задачи» перестаёт давать 404. Снятие assignee членство НЕ удаляет.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project, get_project
from app.api.tasks import create_task, update_task
from app.models.project import ProjectMember
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration


async def _member_role(
    db: AsyncSession, project_id: uuid.UUID, employee_id: uuid.UUID
) -> str | None:
    return (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == employee_id,
            )
        )
    ).scalar_one_or_none()


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Членство {slug}"), owner, db)
    return owner, project


async def test_patch_assignee_creates_viewer_and_fixes_deeplink(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "am1")
    task = await create_task(project.id, TaskCreate(title="Задача"), owner, db)

    stranger = make_principal(
        tenant_id, email="stranger-am1@t.ru", role="member", tenant_slug="am1"
    )
    await _register(db, stranger)
    # До назначения проект для него не существует (404).
    with pytest.raises(Exception) as excinfo:
        await get_project(project.id, stranger, db)
    assert getattr(excinfo.value, "status_code", None) == 404

    await update_task(
        task.id,
        TaskUpdate.model_validate({"assignee_id": stranger.employee_id}),
        owner,
        db,
    )

    assert await _member_role(db, project.id, stranger.employee_id) == "viewer"
    resp = await get_project(project.id, stranger, db)  # deep-link чинится
    assert resp.id == project.id


async def test_assign_existing_editor_keeps_role(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "am2")
    task = await create_task(project.id, TaskCreate(title="Задача"), owner, db)

    editor = make_principal(
        tenant_id, email="editor-am2@t.ru", role="member", tenant_slug="am2"
    )
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    await update_task(
        task.id,
        TaskUpdate.model_validate({"assignee_id": editor.employee_id}),
        owner,
        db,
    )
    assert await _member_role(db, project.id, editor.employee_id) == "editor"


async def test_create_task_with_assignee_creates_membership(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "am3")
    newcomer = make_principal(
        tenant_id, email="new-am3@t.ru", role="member", tenant_slug="am3"
    )
    await _register(db, newcomer)

    await create_task(
        project.id,
        TaskCreate(title="Сразу с исполнителем", assignee_id=newcomer.employee_id),
        owner,
        db,
    )
    assert await _member_role(db, project.id, newcomer.employee_id) == "viewer"


async def test_unassign_keeps_membership(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "am4")
    task = await create_task(project.id, TaskCreate(title="Задача"), owner, db)

    somebody = make_principal(
        tenant_id, email="some-am4@t.ru", role="member", tenant_slug="am4"
    )
    await _register(db, somebody)
    await update_task(
        task.id,
        TaskUpdate.model_validate({"assignee_id": somebody.employee_id}),
        owner,
        db,
    )
    await update_task(
        task.id, TaskUpdate.model_validate({"assignee_id": None}), owner, db
    )
    assert await _member_role(db, project.id, somebody.employee_id) == "viewer"


async def test_backfill_sql_idempotent_and_no_downgrade(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """SQL из 0033: создаёт viewer не-члену, не трогает editor'а, идемпотентен."""
    owner, project = await _seed(db, tenant_id, "am5")

    orphan = make_principal(
        tenant_id, email="orphan-am5@t.ru", role="member", tenant_slug="am5"
    )
    editor = make_principal(
        tenant_id, email="editor-am5@t.ru", role="member", tenant_slug="am5"
    )
    await _register(db, orphan)
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    # Задачи с исполнителями; затем стираем членство orphan'а, имитируя
    # до-релизное состояние (авто-членство ещё не существовало).
    await create_task(
        project.id,
        TaskCreate(title="Сироте", assignee_id=orphan.employee_id),
        owner,
        db,
    )
    await create_task(
        project.id,
        TaskCreate(title="Редактору", assignee_id=editor.employee_id),
        owner,
        db,
    )
    await db.execute(
        sa_text(
            "DELETE FROM project_members WHERE project_id = :pid AND employee_id = :eid"
        ).bindparams(pid=project.id, eid=orphan.employee_id)
    )

    backfill = sa_text(
        """
        INSERT INTO project_members
            (id, tenant_id, project_id, employee_id, role, added_by, added_at)
        SELECT gen_random_uuid(), sub.tenant_id, sub.project_id, sub.assignee_id,
               'viewer', NULL, now()
        FROM (
            SELECT DISTINCT p.tenant_id, t.project_id, t.assignee_id
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            JOIN shadow_users su
              ON su.employee_id = t.assignee_id AND su.deleted_at IS NULL
            WHERE t.assignee_id IS NOT NULL
              AND t.archived_at IS NULL
        ) sub
        ON CONFLICT (project_id, employee_id) DO NOTHING
        """
    )
    await db.execute(backfill)
    assert await _member_role(db, project.id, orphan.employee_id) == "viewer"
    assert await _member_role(db, project.id, editor.employee_id) == "editor"

    await db.execute(backfill)  # повторный прогон — no-op
    assert await _member_role(db, project.id, orphan.employee_id) == "viewer"
