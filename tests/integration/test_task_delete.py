"""Удаление задачи — необратимое и с хвостами, которых не знает каскад БД.

Каскад уносит строки; файлы вложений на диске и уведомления со ссылкой на
задачу — забота ручки. Проверяем и права: удалять могут владелец, редактор и
hub-admin, наблюдатель — нет.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attachments import upload_attachment
from app.api.projects import create_project
from app.api.tasks import create_task, delete_task
from app.config import get_settings
from app.models.attachment import TaskAttachment
from app.models.notification import Notification
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    return tmp_path


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Удаление {slug}"), owner, db)
    await seed_stages(db, project.id, owner, names=("Первая",))
    await db.commit()
    return owner, project


async def _member(db: AsyncSession, tenant_id, project_id, slug: str, role: str):
    person = make_principal(tenant_id, email=f"{role}-{slug}@t.ru", tenant_slug=slug)
    await _register(db, person)
    await _add_member(db, tenant_id, project_id, person, role)
    return person


async def test_editor_can_delete_viewer_cannot(db: AsyncSession, tenant_id: uuid.UUID):
    """Гейт совпал с `can_edit` — кнопка живёт в том же меню, что «В архив»."""
    owner, project = await _seed(db, tenant_id, "del1")
    editor = await _member(db, tenant_id, project.id, "del1", "editor")
    viewer = await _member(db, tenant_id, project.id, "del1", "viewer")

    doomed = await create_task(project.id, TaskCreate(title="Лишняя"), owner, db)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await delete_task(doomed.id, viewer, db)
    assert exc.value.status_code == 403

    await delete_task(doomed.id, editor, db)
    assert await db.get(Task, doomed.id) is None


async def test_parent_takes_subtasks_with_it(db: AsyncSession, tenant_id: uuid.UUID):
    """`tasks.parent_task_id` — ondelete CASCADE: цену называет диалог."""
    owner, project = await _seed(db, tenant_id, "del2")
    parent = await create_task(project.id, TaskCreate(title="Родитель"), owner, db)
    await db.commit()
    child = await create_task(
        project.id, TaskCreate(title="Подзадача", parent_task_id=parent.id), owner, db
    )
    await db.commit()

    await delete_task(parent.id, owner, db)
    assert await db.get(Task, child.id) is None


async def test_attachment_files_leave_the_disk(
    db: AsyncSession, tenant_id: uuid.UUID, storage: Path
):
    """Каскад сносит строки, а файлы вычищает ручка — иначе байты вечны."""
    owner, project = await _seed(db, tenant_id, "del3")
    task = await create_task(project.id, TaskCreate(title="С файлом"), owner, db)
    await db.commit()
    await upload_attachment(
        task.id,
        UploadFile(file=io.BytesIO(PNG), filename="s.png", headers={"content-type": "image/png"}),
        owner,
        db,
    )
    key = (
        await db.execute(
            select(TaskAttachment.storage_key).where(TaskAttachment.task_id == task.id)
        )
    ).scalar_one()
    assert (storage / key).exists()

    await delete_task(task.id, owner, db)
    assert not (storage / key).exists()


async def test_notifications_pointing_at_the_task_are_removed(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Иначе «Входящие» держат строку, которая открывает пустую карточку."""
    owner, project = await _seed(db, tenant_id, "del4")
    task = await create_task(project.id, TaskCreate(title="С уведомлением"), owner, db)
    db.add(
        Notification(
            tenant_id=tenant_id,
            employee_id=owner.employee_id,
            kind="task.assigned_to_me",
            title="Вам назначили задачу",
            body="С уведомлением",
            url=f"/projects/{project.id}?task={task.id}",
        )
    )
    # Чужое уведомление того же проекта обязано выжить.
    db.add(
        Notification(
            tenant_id=tenant_id,
            employee_id=owner.employee_id,
            kind="task.assigned_to_me",
            title="Другая задача",
            body="",
            url=f"/projects/{project.id}?task={uuid.uuid4()}",
        )
    )
    await db.commit()

    await delete_task(task.id, owner, db)
    left = (
        await db.execute(select(Notification.url).where(Notification.tenant_id == tenant_id))
    ).scalars().all()
    assert all(str(task.id) not in url for url in left)
    assert len(left) == 1
