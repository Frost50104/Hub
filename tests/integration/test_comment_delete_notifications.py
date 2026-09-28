"""Удаление комментария снимает его уведомления (ОС 08.09, RH-23).

Заявка: «вижу по уведомлению, что есть два комментария, но второй у задачи не
отображается». Второй комментарий удалил автор через 4 секунды, а уведомления
о нём с цитатой удалённого текста остались во «Входящих» у всех получателей.

Ассерты парные: «уведомление удалённого ушло» рядом с «уведомление живого
осталось» — иначе чистка «всего подряд» прошла бы проверку.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from signaris_auth import Principal
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.comments import create_comment, delete_comment
from app.api.notifications import mark_read
from app.api.projects import create_project
from app.api.tasks import create_task, move_task
from app.db import tenant_scoped_session
from app.models.notification import Notification
from app.schemas.comment import CommentCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskMoveRequest
from app.services.notify import COMMENT_NOTIFICATION_KINDS
from app.services.project_access import ensure_project_member
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register
from tests.integration.test_task_move import _pair

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0064_deleted_comment_notifications.py"
)


def _purge_sql():
    """Ровно тот текст, что выполняет миграция 0064, а не его пересказ."""
    spec = importlib.util.spec_from_file_location("m0064", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PURGE_SQL


def _people(tenant_id: uuid.UUID, tag: str) -> tuple[Principal, Principal, Principal]:
    slug = f"cdn-{tag}-{tenant_id.hex[:8]}"

    def person(name: str) -> Principal:
        return make_principal(
            tenant_id, email=f"{name}-{slug}@t.ru", full_name=name, tenant_slug=slug
        )

    return person("Автор"), person("Наблюдатель"), person("Исполнитель")


async def _comment_rows(db: AsyncSession, task_id: uuid.UUID) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.kind.in_(COMMENT_NOTIFICATION_KINDS),
                    Notification.payload["task_id"].astext == str(task_id),
                )
            )
        )
        .scalars()
        .all()
    )


async def _kind_rows(db: AsyncSession, task_id: uuid.UUID, kind: str) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.kind == kind,
                    Notification.payload["task_id"].astext == str(task_id),
                )
            )
        )
        .scalars()
        .all()
    )


async def _other_kind(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    employee_id: uuid.UUID,
    created_at: datetime | None = None,
) -> None:
    """Уведомление НЕ о комментарии по той же задаче — удаление его не трогает.

    Кладётся напрямую: создание задачи с исполнителем уведомлений не шлёт
    (`services/tasks.py::create_task_record`, notify=False).
    """
    extra = {"created_at": created_at} if created_at is not None else {}
    db.add(
        Notification(
            tenant_id=tenant_id,
            employee_id=employee_id,
            kind="task.assigned_to_me",
            title="Вам назначена задача",
            body="…",
            url=f"/projects/x?task={task_id}",
            payload={"task_id": str(task_id)},
            **extra,
        )
    )
    await db.flush()


async def test_delete_removes_its_notifications_for_every_recipient(rls_enforced):
    """Сессия автора снимает строки ДРУГИХ людей — под настоящим RLS.

    Под superuser'ом testcontainers RLS не действует, и тест не отличил бы
    «политика пускает чужие строки тенанта» от «политики нет».
    """
    tenant_id = uuid.uuid4()
    author, watcher, assignee = _people(tenant_id, "rls")
    async with tenant_scoped_session(tenant_id) as s:
        await _register(s, author, org_role="office")
        await _register(s, watcher)
        await _register(s, assignee)
        await s.commit()
        project = await create_project(ProjectCreate(name="Обсуждения"), author, s)
        task = await create_task(
            project.id,
            TaskCreate(
                title="Оценка компетенции",
                assignee_ids=[watcher.employee_id, assignee.employee_id],
            ),
            author,
            s,
        )
        first = await create_comment(task.id, CommentCreate(body="Первый"), author, s)
        second = await create_comment(task.id, CommentCreate(body="Второй"), author, s)
        for person in (watcher, assignee):
            await _other_kind(
                s, tenant_id=tenant_id, task_id=task.id, employee_id=person.employee_id
            )
        await s.commit()

    async with tenant_scoped_session(tenant_id) as s:
        rows = await _comment_rows(s, task.id)
        # Два комментария × два получателя, у каждой строки — свой комментарий.
        assert len(rows) == 4
        assert {r.payload["comment_id"] for r in rows} == {str(first.id), str(second.id)}
        await delete_comment(first.id, author, s)

    async with tenant_scoped_session(tenant_id) as s:
        rows = await _comment_rows(s, task.id)
        assert {r.employee_id for r in rows} == {watcher.employee_id, assignee.employee_id}
        assert {r.payload["comment_id"] for r in rows} == {str(second.id)}
        # Уведомления других видов по той же задаче удаление не трогает.
        assigned = await _kind_rows(s, task.id, "task.assigned_to_me")
        assert len(assigned) == 2


async def test_legacy_rows_without_comment_id(db: AsyncSession, tenant_id: uuid.UUID):
    """Строки до выката находятся парой (задача, created_at).

    Комментарии — разными вызовами: у каждого своя транзакция и свой `now()`.
    Две legacy-строки, вставленные одним commit, делили бы метку, и тест
    проверял бы не то.
    """
    author, watcher, _ = _people(tenant_id, "legacy")
    await _register(db, author, org_role="office")
    await _register(db, watcher)
    project = await create_project(ProjectCreate(name="Старые строки"), author, db)
    task = await create_task(
        project.id, TaskCreate(title="До выката", assignee_ids=[watcher.employee_id]), author, db
    )
    first = await create_comment(task.id, CommentCreate(body="Первый"), author, db)
    second = await create_comment(task.id, CommentCreate(body="Второй"), author, db)
    assert first.created_at != second.created_at

    await db.execute(
        text(
            "UPDATE notifications SET payload = payload - 'comment_id' "
            "WHERE payload->>'task_id' = :t"
        ),
        {"t": str(task.id)},
    )
    await db.commit()

    await delete_comment(first.id, author, db)

    rows = await _comment_rows(db, task.id)
    assert len(rows) == 1
    assert rows[0].created_at == second.created_at
    assert "comment_id" not in (rows[0].payload or {})


async def test_moved_task_notifications_still_removed(db: AsyncSession, tenant_id: uuid.UUID):
    """Перенос переписывает URL уведомлений, но не payload — чистка находит их."""
    owner, source, target = await _pair(db, tenant_id, "cdnmv")
    # Slug тот же, что у владельца из `_pair`: upsert тенанта переписывает slug.
    watcher = make_principal(
        tenant_id, email=f"watcher-{tenant_id.hex[:8]}@t.ru", tenant_slug="cdnmv"
    )
    await _register(db, watcher)
    task = await create_task(
        source.id, TaskCreate(title="Переезд", assignee_ids=[watcher.employee_id]), owner, db
    )
    # Наблюдатель без членства в цели отписывается при переносе, и его строки
    # уходят вместе с подпиской (`task_move.py`) — тогда проверять было бы нечего.
    await ensure_project_member(
        db,
        project_id=target.id,
        tenant_id=tenant_id,
        employee_id=watcher.employee_id,
        added_by=owner.employee_id,
    )
    await db.commit()
    comment = await create_comment(task.id, CommentCreate(body="До переезда"), owner, db)
    await move_task(task.id, TaskMoveRequest(project_id=target.id), owner, db)

    rows = await _comment_rows(db, task.id)
    assert len(rows) == 1
    assert rows[0].url == f"/projects/{target.id}?task={task.id}"

    await delete_comment(comment.id, owner, db)
    assert await _comment_rows(db, task.id) == []


async def test_migration_sql_purges_only_deleted_comment_notifications(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """SQL миграции 0064 на засеянных данных — прогон `upgrade head` в
    conftest идёт по пустой базе и удаляет ноль строк, то есть не проверяет
    ничего, кроме синтаксиса."""
    author, watcher, _ = _people(tenant_id, "mig")
    await _register(db, author, org_role="office")
    await _register(db, watcher)
    project = await create_project(ProjectCreate(name="Миграция"), author, db)
    task = await create_task(
        project.id, TaskCreate(title="Висящие", assignee_ids=[watcher.employee_id]), author, db
    )
    live = await create_comment(task.id, CommentCreate(body="Живой"), author, db)
    dead = await create_comment(task.id, CommentCreate(body="Удалённый"), author, db)

    # Состояние до исправления: комментарий удалён без чистки, у строк нет
    # comment_id. Плюс уведомление ДРУГОГО вида с той же задачей и меткой —
    # оно обязано уцелеть.
    await db.execute(
        text("UPDATE task_comments SET deleted_at = now() WHERE id = :id"), {"id": dead.id}
    )
    await db.execute(
        text(
            "UPDATE notifications SET payload = payload - 'comment_id' "
            "WHERE payload->>'task_id' = :t"
        ),
        {"t": str(task.id)},
    )
    await _other_kind(
        db,
        tenant_id=tenant_id,
        task_id=task.id,
        employee_id=watcher.employee_id,
        created_at=dead.created_at,
    )
    await db.commit()

    await db.execute(text("SET LOCAL app.bypass_rls = 'on'"))
    await db.execute(_purge_sql())
    await db.commit()

    rows = await _comment_rows(db, task.id)
    assert [r.created_at for r in rows] == [live.created_at]
    assigned = await _kind_rows(db, task.id, "task.assigned_to_me")
    assert len(assigned) == 1
    assert assigned[0].created_at == dead.created_at


async def test_mark_read_is_idempotent(db: AsyncSession, tenant_id: uuid.UUID):
    """Строку могло убрать удаление комментария, пока были открыты «Входящие»:
    клик по ней не должен превращаться в тост об ошибке."""
    author, watcher, _ = _people(tenant_id, "read")
    await _register(db, author, org_role="office")
    await _register(db, watcher)
    project = await create_project(ProjectCreate(name="Прочтение"), author, db)
    task = await create_task(
        project.id, TaskCreate(title="Назначена", assignee_ids=[watcher.employee_id]), author, db
    )
    await _other_kind(db, tenant_id=tenant_id, task_id=task.id, employee_id=watcher.employee_id)
    await db.commit()
    [note] = await _kind_rows(db, task.id, "task.assigned_to_me")
    assert note.is_read is False

    # Нет такой строки — 204 без действий, а не 404.
    await mark_read(note.id + 10_000_000, principal=watcher, db=db)
    # Чужая строка — тот же молчаливый ответ, и она не тронута.
    await mark_read(note.id, principal=author, db=db)
    await db.refresh(note)
    assert note.is_read is False

    await mark_read(note.id, principal=watcher, db=db)
    await db.refresh(note)
    assert note.is_read is True
