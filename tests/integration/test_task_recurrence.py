"""Повтор задач: копия рождается при выполнении, правило переезжает на неё.

Ключевые инварианты, которые тут сторожатся:
1. закрыл задачу — появилась следующая со сдвинутым сроком и скопированным
   содержимым (включая подзадачи, все невыполненными);
2. правило — ТОКЕН: снять галочку и закрыть снова второй копии не даёт;
3. повтор не должен мешать закрывать задачи в архивном проекте и задачи с
   уволенным исполнителем — оба случая через `create_task_record` дали бы
   409/404 прямо внутри закрытия.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import archive_project, create_project
from app.api.tasks import (
    clear_task_recurrence,
    create_task,
    set_task_recurrence,
    update_task,
)
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskLabel, TaskLabelAssignment, TaskRecurrence, TaskWatcher
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskRecurrenceBody, TaskUpdate
from app.services.taskdates import due_day, due_noon_utc
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _project(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(tenant_id, email=f"{slug}-o@t.ru", tenant_slug=slug)
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)
    await seed_stages(db, project.id, owner)
    await db.commit()
    return owner, project


def _due(days: int = 0) -> datetime:
    return due_noon_utc((datetime.now(UTC) + timedelta(days=days)).date())


async def _task_with_rule(
    db: AsyncSession, project_id: uuid.UUID, owner, *, freq: str = "week", step: int = 1, **kw
) -> Task:
    task = await create_task(
        project_id,
        TaskCreate(title=kw.pop("title", "Проверить холодильник"), due_at=_due(), **kw),
        owner,
        db,
    )
    await db.commit()
    await set_task_recurrence(task.id, TaskRecurrenceBody(freq=freq, step=step), owner, db)
    return await db.get(Task, task.id)


async def _close(db: AsyncSession, task_id: uuid.UUID, principal, done: bool = True):
    return await update_task(task_id, TaskUpdate(done=done), principal, db)


async def _children(db: AsyncSession, parent_id: uuid.UUID) -> list[Task]:
    rows = await db.execute(
        select(Task).where(Task.recurrence_parent_id == parent_id).order_by(Task.seq)
    )
    return list(rows.scalars().all())


async def test_closing_spawns_next_copy(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rec-basic")
    task = await _task_with_rule(db, project.id, owner)
    src_due = due_day(task.due_at)

    await _close(db, task.id, owner)

    copies = await _children(db, task.id)
    assert len(copies) == 1
    copy = copies[0]
    assert copy.done is False and copy.completed_at is None
    assert copy.title == task.title
    assert copy.seq != task.seq  # uq_tasks_project_seq: номер всегда свой
    assert due_day(copy.due_at) == src_due + timedelta(days=7)


async def test_rule_moves_to_the_copy(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rec-move")
    task = await _task_with_rule(db, project.id, owner)

    await _close(db, task.id, owner)
    copy = (await _children(db, task.id))[0]

    assert await db.get(TaskRecurrence, task.id) is None
    moved = await db.get(TaskRecurrence, copy.id)
    assert moved is not None
    assert moved.occurrence == 1  # сетка сдвинулась на шаг


async def test_reopen_and_close_again_makes_no_second_copy(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Правило-токен: у исходной задачи его больше нет, создавать нечего."""
    owner, project = await _project(db, tenant_id, "rec-idem")
    task = await _task_with_rule(db, project.id, owner)

    await _close(db, task.id, owner)
    await _close(db, task.id, owner, done=False)
    await _close(db, task.id, owner)

    assert len(await _children(db, task.id)) == 1


async def test_copy_carries_labels_fields_and_assignees(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _project(db, tenant_id, "rec-copy")
    worker = make_principal(tenant_id, email="rec-copy-w@t.ru", tenant_slug="rec-copy")
    await _register(db, worker)
    task = await _task_with_rule(db, project.id, owner, assignee_ids=[worker.employee_id])

    label = TaskLabel(id=uuid.uuid4(), tenant_id=tenant_id, project_id=project.id, name="Смена")
    field = CustomFieldDefinition(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        project_id=project.id,
        name="Точка",
        type="text",
        # `position` NOT NULL и без server_default — в обход ручки его обязан
        # проставить сам тест (иначе NotNullViolationError на flush).
        position=Decimal("1"),
    )
    db.add_all([label, field])
    await db.flush()
    db.add_all(
        [
            TaskLabelAssignment(task_id=task.id, label_id=label.id, tenant_id=tenant_id),
            TaskCustomFieldValue(
                task_id=task.id, field_id=field.id, tenant_id=tenant_id, value="Невская 3"
            ),
        ]
    )
    await db.commit()

    await _close(db, task.id, owner)
    copy = (await _children(db, task.id))[0]

    labels = await db.scalar(
        select(func.count()).select_from(TaskLabelAssignment).where(
            TaskLabelAssignment.task_id == copy.id, TaskLabelAssignment.label_id == label.id
        )
    )
    value = await db.scalar(
        select(TaskCustomFieldValue.value).where(
            TaskCustomFieldValue.task_id == copy.id, TaskCustomFieldValue.field_id == field.id
        )
    )
    assignees = await db.scalar(
        select(func.count()).select_from(Task).where(Task.id == copy.id)
    )
    assert labels == 1
    assert value == "Невская 3"
    assert assignees == 1


async def test_subtasks_are_cloned_undone(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rec-sub")
    task = await _task_with_rule(db, project.id, owner)
    for title in ("Снять показания", "Записать в журнал"):
        sub = await create_task(
            project.id,
            TaskCreate(title=title, parent_task_id=task.id, due_at=_due(1)),
            owner,
            db,
        )
        await update_task(sub.id, TaskUpdate(done=True), owner, db)
    await db.commit()

    await _close(db, task.id, owner)
    copy = (await _children(db, task.id))[0]

    subs = (
        await db.execute(select(Task).where(Task.parent_task_id == copy.id).order_by(Task.seq))
    ).scalars().all()
    assert len(subs) == 2
    # Подзадачи приходят «как чек-лист» — все невыполненными, даже если в
    # прошлый раз их закрыли.
    assert all(s.done is False for s in subs)
    assert len({s.seq for s in subs}) == 2


async def test_manual_watcher_is_not_carried_over(db: AsyncSession, tenant_id: uuid.UUID):
    """Подписка на КОНКРЕТНУЮ задачу, а не на бесконечную серию."""
    owner, project = await _project(db, tenant_id, "rec-watch")
    task = await _task_with_rule(db, project.id, owner)
    outsider = make_principal(tenant_id, email="rec-watch-x@t.ru", tenant_slug="rec-watch")
    await _register(db, outsider)
    db.add(
        TaskWatcher(
            task_id=task.id,
            employee_id=outsider.employee_id,
            tenant_id=tenant_id,
            added_reason="manual",
        )
    )
    await db.commit()

    await _close(db, task.id, owner)
    copy = (await _children(db, task.id))[0]

    carried = await db.scalar(
        select(func.count()).select_from(TaskWatcher).where(
            TaskWatcher.task_id == copy.id, TaskWatcher.employee_id == outsider.employee_id
        )
    )
    assert carried == 0


async def test_closing_survives_archived_project(db: AsyncSession, tenant_id: uuid.UUID):
    """Гейт создания задач отвечает 409 — закрытие задачи он ронять не должен."""
    owner, project = await _project(db, tenant_id, "rec-arch")
    task = await _task_with_rule(db, project.id, owner)
    await archive_project(project.id, owner, db)

    await _close(db, task.id, owner)  # не бросает

    fresh = await db.get(Task, task.id)
    assert fresh.done is True
    assert await _children(db, task.id) == []
    assert await db.get(TaskRecurrence, task.id) is None  # серия остановлена


async def test_closing_survives_deleted_assignee(db: AsyncSession, tenant_id: uuid.UUID):
    """Уволенный в auth исполнитель не должен мешать закрыть задачу."""
    owner, project = await _project(db, tenant_id, "rec-fired")
    fired = make_principal(tenant_id, email="rec-fired-x@t.ru", tenant_slug="rec-fired")
    await _register(db, fired)
    task = await _task_with_rule(db, project.id, owner, assignee_ids=[fired.employee_id])
    shadow = await db.get(ShadowUser, fired.employee_id)
    shadow.deleted_at = datetime.now(UTC)
    await db.commit()

    await _close(db, task.id, owner)  # через create_task_record тут был бы 404

    copy = (await _children(db, task.id))[0]
    assert copy is not None


async def test_recurrence_gates(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rec-gates")

    no_due = await create_task(project.id, TaskCreate(title="Без срока"), owner, db)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await set_task_recurrence(no_due.id, TaskRecurrenceBody(freq="day"), owner, db)
    assert exc.value.status_code == 422

    parent = await _task_with_rule(db, project.id, owner, title="Родитель")
    sub = await create_task(
        project.id,
        TaskCreate(title="Подзадача", parent_task_id=parent.id, due_at=_due()),
        owner,
        db,
    )
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await set_task_recurrence(sub.id, TaskRecurrenceBody(freq="day"), owner, db)
    assert exc.value.status_code == 409

    # Уже породившая задача повтор обратно не принимает: правило уехало.
    await _close(db, parent.id, owner)
    with pytest.raises(HTTPException) as exc:
        await set_task_recurrence(parent.id, TaskRecurrenceBody(freq="day"), owner, db)
    assert exc.value.status_code == 409


async def test_assignee_viewer_closes_but_cannot_set_rule(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Расписание — планирование: исполнитель закрывает, но правил не ставит."""
    owner, project = await _project(db, tenant_id, "rec-role")
    worker = make_principal(tenant_id, email="rec-role-w@t.ru", tenant_slug="rec-role")
    await _register(db, worker)
    task = await _task_with_rule(db, project.id, owner, assignee_ids=[worker.employee_id])

    with pytest.raises(HTTPException) as exc:
        await set_task_recurrence(task.id, TaskRecurrenceBody(freq="day"), worker, db)
    assert exc.value.status_code == 403

    await _close(db, task.id, worker)
    assert len(await _children(db, task.id)) == 1


async def test_clear_is_idempotent(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rec-clear")
    task = await _task_with_rule(db, project.id, owner)

    await clear_task_recurrence(task.id, owner, db)
    await clear_task_recurrence(task.id, owner, db)  # повтор — не ошибка

    assert await db.get(TaskRecurrence, task.id) is None
    await _close(db, task.id, owner)
    assert await _children(db, task.id) == []


async def test_deleting_source_keeps_the_copy(db: AsyncSession, tenant_id: uuid.UUID):
    """ON DELETE SET NULL, а не CASCADE: цепочка не должна уходить за предком."""
    owner, project = await _project(db, tenant_id, "rec-del")
    task = await _task_with_rule(db, project.id, owner)
    await _close(db, task.id, owner)
    copy = (await _children(db, task.id))[0]

    await db.delete(await db.get(Task, task.id))
    await db.commit()

    assert await db.get(Task, copy.id) is not None
    # Значение читаем колонкой, а не атрибутом объекта: `SET NULL` делает
    # Postgres по FK, сессия живёт с `expire_on_commit=False` и отдала бы
    # закешированного предка.
    parent = await db.scalar(select(Task.recurrence_parent_id).where(Task.id == copy.id))
    assert parent is None
