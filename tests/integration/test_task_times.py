"""Время у старта и срока задачи (0061) на живой БД.

Сторожит:
1. правило пары (мгновение, флаг) в PATCH — включая время 12:00, которое даёт
   то же мгновение, что день без времени;
2. дата без флага (старый бандл, CSV, ассистент) снимает время, флаг без даты — 422;
3. CHECK «время без даты не бывает» держит БД;
4. копия по повтору сохраняет выбранный час;
5. публичный срез отдаёт флаг.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public import _build_project_view, _build_task_view
from app.api.tasks import create_task, set_task_recurrence, update_task
from app.models.task import Task, TaskActivity
from app.schemas.task import TaskCreate, TaskRecurrenceBody, TaskUpdate
from app.services.taskdates import due_noon_utc
from tests.integration.test_task_recurrence import _children, _project

pytestmark = pytest.mark.integration

MSK = ZoneInfo("Europe/Moscow")


def _at(days: int, hh: int, mm: int = 0) -> datetime:
    day = (datetime.now(MSK) + timedelta(days=days)).date()
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=MSK).astimezone(UTC)


async def _task(db: AsyncSession, project_id: uuid.UUID, owner, **kw) -> Task:
    created = await create_task(project_id, TaskCreate(title="Сдать отчёт", **kw), owner, db)
    await db.commit()
    task = await db.get(Task, created.id)
    assert task is not None
    return task


async def test_patch_sets_and_drops_time(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-patch")
    task = await _task(db, project.id, owner)

    resp = await update_task(
        task.id, TaskUpdate(due_at=_at(2, 15), due_has_time=True), owner, db
    )
    assert (resp.due_at, resp.due_has_time) == (_at(2, 15), True)

    # Дата без флага — так пишет старый бандл: время снимается.
    resp = await update_task(task.id, TaskUpdate(due_at=due_noon_utc(_at(3, 12).date())), owner, db)
    assert resp.due_has_time is False

    # Снятие срока снимает и флаг (иначе CHECK).
    await update_task(task.id, TaskUpdate(due_at=_at(3, 9), due_has_time=True), owner, db)
    resp = await update_task(task.id, TaskUpdate(due_at=None, due_has_time=True), owner, db)
    assert (resp.due_at, resp.due_has_time) == (None, False)


async def test_noon_time_is_recorded(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-noon")
    noon = due_noon_utc(_at(2, 12).date())
    task = await _task(db, project.id, owner, due_at=noon)
    assert task.due_has_time is False

    # Тот же момент, но теперь это выбранное время «12:00».
    resp = await update_task(task.id, TaskUpdate(due_at=noon, due_has_time=True), owner, db)
    assert resp.due_has_time is True
    rows = await db.execute(
        select(TaskActivity.payload).where(
            TaskActivity.task_id == task.id, TaskActivity.kind == "updated"
        )
    )
    payloads = [p for (p,) in rows.all()]
    assert any(p.get("due_at", {}).get("new_has_time") is True for p in payloads)


async def test_flag_without_date_is_422(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-422")
    task = await _task(db, project.id, owner, due_at=_at(2, 15), due_has_time=True)
    with pytest.raises(HTTPException) as exc:
        await update_task(task.id, TaskUpdate(due_has_time=False), owner, db)
    assert exc.value.status_code == 422
    await db.rollback()
    with pytest.raises(HTTPException) as exc:
        await create_task(project.id, TaskCreate(title="X", start_has_time=True), owner, db)
    assert exc.value.status_code == 422


async def test_create_with_start_and_due_time(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-create")
    task = await _task(
        db,
        project.id,
        owner,
        start_at=_at(1, 9),
        start_has_time=True,
        due_at=_at(1, 18),
        due_has_time=True,
    )
    assert (task.start_has_time, task.due_has_time) == (True, True)


async def test_check_constraint_guards_time_without_date(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _project(db, tenant_id, "tt-check")
    task = await _task(db, project.id, owner)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE tasks SET due_has_time = true WHERE id = :id"), {"id": task.id}
        )
    await db.rollback()


async def test_recurrence_copy_keeps_hour(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-rec")
    task = await _task(db, project.id, owner, due_at=_at(0, 15, 30), due_has_time=True)
    await set_task_recurrence(task.id, TaskRecurrenceBody(freq="day", step=1), owner, db)
    await update_task(task.id, TaskUpdate(done=True), owner, db)

    [copy] = await _children(db, task.id)
    local = copy.due_at.astimezone(MSK)
    assert copy.due_has_time is True
    assert (local.hour, local.minute) == (15, 30)
    assert local.date() > datetime.now(MSK).date()


async def test_public_views_carry_flag(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "tt-pub")
    task = await _task(db, project.id, owner, due_at=_at(2, 15), due_has_time=True)
    view = await _build_task_view(db, task.id)
    assert view.due_has_time is True
    project_view = await _build_project_view(db, project.id)
    hits = [h for s in project_view.sections for h in s.tasks]
    assert [h.due_has_time for h in hits if h.id == task.id] == [True]
