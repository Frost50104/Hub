"""Наблюдатели: редакторское управление составом (02.09).

Добавление ДРУГОГО человека — выдача доступа: не-участник получает
viewer-членство и открывает задачу по ссылке из пуша. Гейт — owner/editor
(как у назначения исполнителей); себя снимает любой наблюдатель.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.comments import create_comment
from app.api.projects import create_project
from app.api.tasks import create_task, get_task
from app.api.watchers import add_watcher, leave_watching, remove_watcher
from app.models.notification import Notification
from app.models.project import ProjectMember
from app.models.task import TaskWatcher
from app.schemas.comment import CommentCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.schemas.watcher import WatcherAddBody
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _setup(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """(владелец, viewer-участник, посторонний, проект, задача)."""
    owner = make_principal(tenant_id, email=f"{slug}-o@t.ru", tenant_slug=slug)
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)

    viewer = make_principal(tenant_id, email=f"{slug}-v@t.ru", tenant_slug=slug)
    outsider = make_principal(tenant_id, email=f"{slug}-x@t.ru", tenant_slug=slug)
    for p in (viewer, outsider):
        await _register(db, p)
    db.add(
        ProjectMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            project_id=project.id,
            employee_id=viewer.employee_id,
            role="viewer",
            added_by=owner.employee_id,
        )
    )
    task = await create_task(project.id, TaskCreate(title="Обсудить бюджет"), owner, db)
    await db.commit()
    return owner, viewer, outsider, project, task


async def _watchers(db: AsyncSession, task_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task_id)
            )
        ).scalars()
    )


async def test_editor_adds_outsider_who_gains_point_access(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Владелец подписывает постороннего: watcher + viewer-членство, задача
    открывается, комментарий доступен, пуш о чужом комментарии доходит."""
    owner, _viewer, outsider, project, task = await _setup(db, tenant_id, "wt1")

    resp = await add_watcher(
        task.id, WatcherAddBody(employee_id=outsider.employee_id), owner, db
    )
    assert resp.employee_id == outsider.employee_id

    assert outsider.employee_id in await _watchers(db, task.id)
    role = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.employee_id == outsider.employee_id,
            )
        )
    ).scalar_one()
    assert role == "viewer"

    # Ссылка из пуша теперь открывается: карточка и комментарии доступны.
    fetched = await get_task(task.id, outsider, db)
    assert fetched.id == task.id
    await create_comment(task.id, CommentCreate(body="Спасибо, посмотрю"), outsider, db)

    # Комментарий владельца пушится добавленному наблюдателю.
    await create_comment(task.id, CommentCreate(body="Взяли в работу"), owner, db)
    kinds = (
        await db.execute(
            select(Notification.kind).where(
                Notification.employee_id == outsider.employee_id
            )
        )
    ).scalars().all()
    assert "task.commented_on_watched" in kinds


async def test_viewer_cannot_manage_watchers(db: AsyncSession, tenant_id: uuid.UUID):
    """Управление составом — редакторское право: viewer получает 403."""
    _owner, viewer, outsider, _project, task = await _setup(db, tenant_id, "wt2")
    with pytest.raises(HTTPException) as exc:
        await add_watcher(
            task.id, WatcherAddBody(employee_id=outsider.employee_id), viewer, db
        )
    assert exc.value.status_code == 403


async def test_editor_removes_watcher_self_leave_still_works(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Редактор снимает другого; членство остаётся (как у исполнителей);
    самоотписка колокольчиком жива."""
    owner, viewer, outsider, project, task = await _setup(db, tenant_id, "wt3")
    await add_watcher(
        task.id, WatcherAddBody(employee_id=outsider.employee_id), owner, db
    )

    await remove_watcher(task.id, outsider.employee_id, owner, db)
    assert outsider.employee_id not in await _watchers(db, task.id)
    # Членство пережило снятие — доступ не отзываем молча.
    role = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.employee_id == outsider.employee_id,
            )
        )
    ).scalar_one()
    assert role == "viewer"

    # Самоотписка: viewer подписался сам (create_task его не подписывал) — и ушёл.
    await add_watcher(task.id, WatcherAddBody(employee_id=viewer.employee_id), owner, db)
    await leave_watching(task.id, viewer, db)
    assert viewer.employee_id not in await _watchers(db, task.id)


async def test_add_is_idempotent_and_unknown_target_404(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, viewer, _outsider, _project, task = await _setup(db, tenant_id, "wt4")
    await add_watcher(task.id, WatcherAddBody(employee_id=viewer.employee_id), owner, db)
    # Повторное добавление — не ошибка (ON CONFLICT DO NOTHING).
    await add_watcher(task.id, WatcherAddBody(employee_id=viewer.employee_id), owner, db)
    assert (await _watchers(db, task.id)).count(viewer.employee_id) == 1

    with pytest.raises(HTTPException) as exc:
        await add_watcher(
            task.id, WatcherAddBody(employee_id=uuid.uuid4()), owner, db
        )
    assert exc.value.status_code == 404
