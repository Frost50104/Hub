"""Удаление проекта — единственное необратимое действие продукта.

Проверяем не «удалилось ли», а то, что нельзя откатить кнопкой: полноту
каскада, границу тенанта у таблицы БЕЗ RLS, снятие файлов с диска и живучесть
записи аудита после исчезновения объекта.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project, delete_project, get_project
from app.api.tasks import create_task
from app.models.audit import AuditLog
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.share import PublicShareToken
from app.models.task import Task, TaskActivity, TaskAssignee, TaskComment, TaskWatcher
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Удаляемый {slug}"), owner, db)
    task = await create_task(project.id, TaskCreate(title="Задача"), owner, db)
    await create_task(
        project.id, TaskCreate(title="Подзадача", parent_task_id=task.id), owner, db
    )
    await db.commit()
    return owner, project, task


async def _count(db: AsyncSession, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await db.execute(stmt)).scalar_one()


async def test_delete_cascades_children(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, task = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    assert await _count(db, Task, Task.project_id == project.id) == 2

    await delete_project(project.id, key=project.key, principal=owner, db=db)

    assert await _count(db, Project, Project.id == project.id) == 0
    assert await _count(db, Task, Task.project_id == project.id) == 0
    assert await _count(db, ProjectMember, ProjectMember.project_id == project.id) == 0
    # Дочерние сущности задачи уходят вторым порядком каскада.
    assert await _count(db, TaskAssignee, TaskAssignee.task_id == task.id) == 0
    assert await _count(db, TaskWatcher, TaskWatcher.task_id == task.id) == 0
    assert await _count(db, TaskComment, TaskComment.task_id == task.id) == 0
    assert await _count(db, TaskActivity, TaskActivity.task_id == task.id) == 0


async def test_delete_removes_share_tokens_but_spares_other_tenant(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """`public_share_tokens` — таблица БЕЗ RLS.

    Это единственное место продукта, где DELETE может выйти за тенант, поэтому
    явный `tenant_id` в WHERE — не украшение.
    """
    owner, project, task = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    other_tenant = uuid.uuid4()
    for scope, entity, tid in (
        ("project", project.id, tenant_id),
        ("task", task.id, tenant_id),
        # Чужой тенант, но ТОТ ЖЕ entity_id — ловушка на забытый tenant_id.
        ("project", project.id, other_tenant),
    ):
        db.add(
            PublicShareToken(
                id=uuid.uuid4(),
                tenant_id=tid,
                scope=scope,
                entity_id=entity,
                created_by=owner.employee_id,
            )
        )
    await db.commit()

    await delete_project(project.id, key=project.key, principal=owner, db=db)

    assert await _count(db, PublicShareToken, PublicShareToken.tenant_id == tenant_id) == 0
    assert (
        await _count(db, PublicShareToken, PublicShareToken.tenant_id == other_tenant)
        == 1
    )


async def test_delete_removes_notifications_of_this_project_only(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, _task = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    stranger = uuid.uuid4()
    for url in (
        f"/projects/{project.id}?task={uuid.uuid4()}",
        f"/projects/{project.id}",
        f"/projects/{stranger}?task={uuid.uuid4()}",
    ):
        db.add(
            Notification(
                tenant_id=tenant_id,
                employee_id=owner.employee_id,
                kind="task.assigned_to_me",
                title="т",
                body="т",
                url=url,
            )
        )
    await db.commit()

    await delete_project(project.id, key=project.key, principal=owner, db=db)

    assert await _count(db, Notification, Notification.url.like(f"/projects/{project.id}%")) == 0
    assert await _count(db, Notification, Notification.url.like(f"/projects/{stranger}%")) == 1


async def test_audit_row_survives_the_object(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    key, name = project.key, project.name

    await delete_project(project.id, key=key, principal=owner, db=db)

    row = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_type == "project", AuditLog.object_id == project.id
            )
        )
    ).scalar_one()
    assert row.action == "delete"
    # object_label задуман именно для этого: объекта уже нет, имя осталось.
    assert key in (row.object_label or "") and name in (row.object_label or "")
    assert (row.diff or {}).get("tasks") == 2


async def test_wrong_key_is_409_and_project_survives(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc:
        await delete_project(project.id, key="НЕВЕРНО", principal=owner, db=db)
    assert exc.value.status_code == 409
    await db.rollback()
    assert await _count(db, Project, Project.id == project.id) == 1


async def test_editor_cannot_delete(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    slug = uuid.uuid4().hex[:6]
    editor = make_principal(
        tenant_id, email=f"ed-{slug}@t.ru", tenant_slug=f"ed{slug}"
    )
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    with pytest.raises(HTTPException) as exc:
        await delete_project(project.id, key=project.key, principal=editor, db=db)
    assert exc.value.status_code == 403


async def test_hub_admin_outside_membership_can_delete(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    slug = uuid.uuid4().hex[:6]
    admin = make_principal(
        tenant_id, email=f"adm-{slug}@t.ru", role="admin", tenant_slug=f"adm{slug}"
    )
    await _register(db, admin)

    await delete_project(project.id, key=project.key, principal=admin, db=db)
    assert await _count(db, Project, Project.id == project.id) == 0


async def test_personal_project_cannot_be_deleted(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Иначе `ensure_personal_project` завёл бы пустой новый, а история ушла."""
    from app.services.personal_projects import ensure_personal_project

    slug = uuid.uuid4().hex[:6]
    owner = make_principal(
        tenant_id, email=f"p-{slug}@t.ru", tenant_slug=f"pers{slug}"
    )
    await _register(db, owner)
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    assert personal_id is not None
    personal = await db.get(Project, personal_id)

    with pytest.raises(HTTPException) as exc:
        await delete_project(personal_id, key=personal.key, principal=owner, db=db)
    assert exc.value.status_code == 409


async def test_get_project_after_delete_is_404(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    await delete_project(project.id, key=project.key, principal=owner, db=db)

    with pytest.raises(HTTPException) as exc:
        await get_project(project.id, owner, db)
    assert exc.value.status_code == 404


async def test_create_task_in_deleted_project_is_404_not_500(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Регресс: `allocate_task_seq` делал `scalar_one()` и бросал 500."""
    owner, project, _ = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    await delete_project(project.id, key=project.key, principal=owner, db=db)

    with pytest.raises(HTTPException) as exc:
        await create_task(project.id, TaskCreate(title="Поздняя"), owner, db)
    assert exc.value.status_code == 404


async def test_attachment_blobs_are_unlinked(
    db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, monkeypatch
):
    from app.config import get_settings
    from app.models.attachment import TaskAttachment
    from app.services.attachments import absolute_path

    settings = get_settings()
    monkeypatch.setattr(settings, "attachments_root", tmp_path)

    owner, project, task = await _seed(db, tenant_id, f"d{uuid.uuid4().hex[:6]}")
    key = f"{tenant_id}/{task.id}/deadbeef-f.png"
    path = absolute_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    db.add(
        TaskAttachment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            task_id=task.id,
            filename="f.png",
            mime="image/png",
            size_bytes=8,
            storage_key=key,
            uploaded_by=owner.employee_id,
        )
    )
    await db.commit()
    assert path.is_file()

    await delete_project(project.id, key=project.key, principal=owner, db=db)

    assert not path.exists()
    assert not path.parent.exists()  # пустой каталог задачи убран
