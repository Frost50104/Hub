"""Личные напоминания по задачам (0062) на живой БД: ручки, тик, перенос срока.

Сторожит:
1. ставит любой, кто видит задачу (viewer тоже), видит только свои; честные
   отказы (прошлое, нет срока, архив, выполнена, потолок) — сразу, а не тостом;
2. тик отправляет ровно один раз: разовое удаляется, правило засыпает и
   взводится снова при переносе срока;
3. выполненная задача, исключённый из проекта, чужое личное — без отправки;
4. повтор переносит правило на копию, разовое остаётся;
5. одна упавшая строка не держит очередь.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import archive_project
from app.api.task_reminders import (
    ReminderCreate,
    create_task_reminder,
    delete_task_reminder,
    list_task_reminders,
)
from app.api.tasks import create_task, set_task_recurrence, update_task
from app.models.notification import Notification, NotificationPreferences
from app.models.project import ProjectMember
from app.models.task import TaskReminder
from app.schemas.task import TaskCreate, TaskRecurrenceBody, TaskUpdate
from app.services import task_reminders as tr
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register
from tests.integration.test_task_recurrence import _children, _project

pytestmark = pytest.mark.integration

MSK = ZoneInfo("Europe/Moscow")


def _in(minutes: int) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _at_local(days: int, hh: int, mm: int = 0) -> datetime:
    day = (datetime.now(MSK) + timedelta(days=days)).date()
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=MSK).astimezone(UTC)


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list:
    """Пуши не уходят наружу: копим задания тика."""
    captured: list = []
    monkeypatch.setattr(tr, "_schedule_pushes", lambda jobs: captured.extend(jobs))
    return captured


async def _task(db: AsyncSession, project_id: uuid.UUID, owner, **kw) -> uuid.UUID:
    """id, а не ORM-объект: после `rollback()` объект протухает, и обращение к
    его атрибуту полезло бы в БД вне greenlet'а (MissingGreenlet)."""
    created = await create_task(project_id, TaskCreate(title="Сдать отчёт", **kw), owner, db)
    await db.commit()
    return created.id


async def _remind(db, task_id, principal, **kw):
    return await create_task_reminder(task_id, ReminderCreate(**kw), principal, db)


async def _rows(db: AsyncSession, task_id: uuid.UUID) -> list[TaskReminder]:
    # Тик и ручки пишут в СВОИХ сессиях — свежие значения поверх identity map.
    rows = await db.execute(
        select(TaskReminder)
        .where(TaskReminder.task_id == task_id)
        .order_by(TaskReminder.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


async def _inbox(db: AsyncSession, employee_id: uuid.UUID) -> list[Notification]:
    rows = await db.execute(
        select(Notification).where(
            Notification.employee_id == employee_id, Notification.kind == tr.KIND
        )
    )
    return list(rows.scalars().all())


# ─── Ручки ──────────────────────────────────────────────────────────────────


async def test_viewer_sets_own_reminder_and_sees_only_own(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _project(db, tenant_id, "rm-view")
    viewer = make_principal(tenant_id, email="rm-view-v@t.ru", tenant_slug="rm-view")
    await _register(db, viewer)
    await _add_member(db, tenant_id, project.id, viewer, "viewer")
    task = await _task(db, project.id, owner, due_at=_at_local(2, 15), due_has_time=True)

    await _remind(db, task, owner, anchor="due", offset_minutes=60)
    resp = await _remind(db, task, viewer, anchor="at", fire_at=_in(90))
    assert [i.anchor for i in resp.items] == ["at"]
    assert resp.items[0].state == "armed"

    mine = await list_task_reminders(task, owner, db)
    assert [(i.anchor, i.offset_minutes) for i in mine.items] == [("due", 60)]
    assert mine.items[0].fire_at == _at_local(2, 14)
    assert mine.delivery.push_devices == 0


async def test_honest_refusals(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rm-no")
    task = await _task(db, project.id, owner)

    for kw, code in (
        ({"anchor": "at", "fire_at": _in(-10)}, 422),
        ({"anchor": "at"}, 422),
        ({"anchor": "due", "offset_minutes": 60}, 422),
        ({"anchor": "start"}, 422),
    ):
        with pytest.raises(HTTPException) as exc:
            await _remind(db, task, owner, **kw)
        assert exc.value.status_code == code, kw
        await db.rollback()

    for n in range(5):
        await _remind(db, task, owner, anchor="at", fire_at=_in(60 + n))
    with pytest.raises(HTTPException) as exc:
        await _remind(db, task, owner, anchor="at", fire_at=_in(70))
    assert exc.value.status_code == 409
    await db.rollback()

    done = await _task(db, project.id, owner)
    await update_task(done, TaskUpdate(done=True), owner, db)
    with pytest.raises(HTTPException) as exc:
        await _remind(db, done, owner, anchor="at", fire_at=_in(60))
    assert exc.value.status_code == 409
    await db.rollback()

    await archive_project(project.id, owner, db)
    with pytest.raises(HTTPException) as exc:
        await _remind(db, task, owner, anchor="at", fire_at=_in(60))
    assert exc.value.status_code == 409


async def test_double_click_is_one_row_and_delete_is_idempotent(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _project(db, tenant_id, "rm-dup")
    task = await _task(db, project.id, owner)
    # Минута — единица выбора: второй клик в ту же минуту — та же строка.
    moment = _in(120).replace(second=10, microsecond=0)
    await _remind(db, task, owner, anchor="at", fire_at=moment)
    resp = await _remind(db, task, owner, anchor="at", fire_at=moment + timedelta(seconds=20))
    assert len(resp.items) == 1
    rid = resp.items[0].id
    await delete_task_reminder(task, rid, owner, db)
    await delete_task_reminder(task, rid, owner, db)  # второй раз — тоже 204
    assert await _rows(db, task) == []


async def test_feature_off_is_404(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    owner, project = await _project(db, tenant_id, "rm-off")
    task = await _task(db, project.id, owner)
    monkeypatch.setenv("SIGNARIS_HUB_TASK_REMINDERS_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc:
            await list_task_reminders(task, owner, db)
        assert exc.value.status_code == 404
    finally:
        get_settings.cache_clear()


# ─── Тик ────────────────────────────────────────────────────────────────────


async def test_at_fires_once(db: AsyncSession, tenant_id: uuid.UUID, pushes: list):
    owner, project = await _project(db, tenant_id, "rm-at")
    task = await _task(db, project.id, owner, due_at=_at_local(1, 15), due_has_time=True)
    await _remind(db, task, owner, anchor="at", fire_at=_in(5))

    counts = await tr.tick(_in(6), tenant_id=tenant_id)
    assert counts.get("fired") == 1
    assert await _rows(db, task) == []
    [note] = await _inbox(db, owner.employee_id)
    assert note.title == "Напоминание"
    assert note.body.startswith("«Сдать отчёт» — срок завтра в 15:00")
    assert note.url == f"/projects/{project.id}?task={task}"
    assert [j.employee_id for j in pushes] == [owner.employee_id]

    assert (await tr.tick(_in(7), tenant_id=tenant_id)).get("fired") is None
    assert len(await _inbox(db, owner.employee_id)) == 1


async def test_rule_sleeps_after_firing_and_rearms_on_move(
    db: AsyncSession, tenant_id: uuid.UUID, pushes: list
):
    owner, project = await _project(db, tenant_id, "rm-rule")
    due = _in(60).replace(second=0, microsecond=0)
    task = await _task(db, project.id, owner, due_at=due, due_has_time=True)
    await _remind(db, task, owner, anchor="due", offset_minutes=0)

    await tr.tick(due + timedelta(seconds=7), tenant_id=tenant_id)  # «к сроку» в 7 с после
    [row] = await _rows(db, task)
    assert (row.fire_at, row.fired_anchor_at) == (None, due)
    assert len(await _inbox(db, owner.employee_id)) == 1

    new_due = due + timedelta(days=1)
    await update_task(task, TaskUpdate(due_at=new_due, due_has_time=True), owner, db)
    [row] = await _rows(db, task)
    assert row.fire_at == new_due


async def test_moving_deadline_moves_reminder(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rm-move")
    task = await _task(db, project.id, owner, due_at=_at_local(3, 15), due_has_time=True)
    await _remind(db, task, owner, anchor="due", offset_minutes=60)
    await update_task(task, TaskUpdate(due_at=_at_local(4, 18), due_has_time=True), owner, db)
    [row] = await _rows(db, task)
    assert row.fire_at == _at_local(4, 17)

    # Сняли срок — правило спит; вернули — ожило.
    await update_task(task, TaskUpdate(due_at=None), owner, db)
    [row] = await _rows(db, task)
    assert row.fire_at is None
    listed = await list_task_reminders(task, owner, db)
    assert listed.items[0].state == "no_date"
    await update_task(task, TaskUpdate(due_at=_at_local(5, 10), due_has_time=True), owner, db)
    [row] = await _rows(db, task)
    assert row.fire_at == _at_local(5, 9)


async def test_done_task_and_lost_access_do_not_fire(
    db: AsyncSession, tenant_id: uuid.UUID, pushes: list
):
    owner, project = await _project(db, tenant_id, "rm-skip")
    viewer = make_principal(tenant_id, email="rm-skip-v@t.ru", tenant_slug="rm-skip")
    await _register(db, viewer)
    await _add_member(db, tenant_id, project.id, viewer, "viewer")
    task = await _task(db, project.id, owner)
    await _remind(db, task, owner, anchor="at", fire_at=_in(5))
    await _remind(db, task, viewer, anchor="at", fire_at=_in(5))

    await update_task(task, TaskUpdate(done=True), owner, db)
    await update_task(task, TaskUpdate(done=False), owner, db)  # вернули в работу
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.employee_id == viewer.employee_id,
        )
    )
    await db.commit()

    counts = await tr.tick(_in(6), tenant_id=tenant_id)
    assert counts.get("fired") == 1  # владелец: задача снова в работе
    assert counts.get("no_access") == 1  # исключённый из проекта
    assert await _inbox(db, viewer.employee_id) == []

    done = await _task(db, project.id, owner)
    await _remind(db, done, owner, anchor="at", fire_at=_in(5))
    await update_task(done, TaskUpdate(done=True), owner, db)
    counts = await tr.tick(_in(6), tenant_id=tenant_id)
    assert counts.get("dropped") == 1
    assert len(await _inbox(db, owner.employee_id)) == 1


async def test_admin_outside_membership_gets_reminder(
    db: AsyncSession, tenant_id: uuid.UUID, pushes: list
):
    owner, project = await _project(db, tenant_id, "rm-adm")
    admin = make_principal(tenant_id, email="rm-adm-a@t.ru", role="admin", tenant_slug="rm-adm")
    await _register(db, admin)
    task = await _task(db, project.id, owner)
    await _remind(db, task, admin, anchor="at", fire_at=_in(5))
    [row] = await _rows(db, task)
    assert row.via_admin is True
    assert (await tr.tick(_in(6), tenant_id=tenant_id)).get("fired") == 1


async def test_inapp_off_push_on_still_pushes(
    db: AsyncSession, tenant_id: uuid.UUID, pushes: list
):
    owner, project = await _project(db, tenant_id, "rm-pref")
    db.add(
        NotificationPreferences(
            employee_id=owner.employee_id,
            tenant_id=tenant_id,
            prefs={tr.KIND: {"push": True, "in_app": False}},
        )
    )
    await db.commit()
    task = await _task(db, project.id, owner)
    await _remind(db, task, owner, anchor="at", fire_at=_in(5))
    await tr.tick(_in(6), tenant_id=tenant_id)
    assert await _inbox(db, owner.employee_id) == []
    assert [j.employee_id for j in pushes] == [owner.employee_id]
    # Строка-токен удалена: повторного пуша через тик не будет.
    await tr.tick(_in(7), tenant_id=tenant_id)
    assert len(pushes) == 1


async def test_failing_row_does_not_block_queue(
    db: AsyncSession, tenant_id: uuid.UUID, pushes: list, monkeypatch: pytest.MonkeyPatch
):
    owner, project = await _project(db, tenant_id, "rm-fail")
    first = await _task(db, project.id, owner)
    second = await _task(db, project.id, owner)
    await _remind(db, first, owner, anchor="at", fire_at=_in(4))
    await _remind(db, second, owner, anchor="at", fire_at=_in(5))

    real = tr.queue_many
    calls = {"n": 0}

    async def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("сбой одной строки")
        return await real(*a, **kw)

    monkeypatch.setattr(tr, "queue_many", flaky)
    counts = await tr.tick(_in(6), tenant_id=tenant_id)
    assert (counts.get("failed"), counts.get("fired")) == (1, 1)
    [postponed] = await _rows(db, first)
    assert postponed.fire_at > _in(8)


# ─── Повтор ─────────────────────────────────────────────────────────────────


async def test_recurrence_moves_rule_to_copy(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project(db, tenant_id, "rm-rec")
    task = await _task(db, project.id, owner, due_at=_at_local(0, 23, 30), due_has_time=True)
    await set_task_recurrence(task, TaskRecurrenceBody(freq="day", step=1), owner, db)
    await _remind(db, task, owner, anchor="due", offset_minutes=15)
    await _remind(db, task, owner, anchor="at", fire_at=_in(600))

    await update_task(task, TaskUpdate(done=True), owner, db)
    [copy] = await _children(db, task)
    assert [r.anchor for r in await _rows(db, task)] == ["at"]
    [moved] = await _rows(db, copy.id)
    assert (moved.anchor, moved.offset_minutes, moved.fired_anchor_at) == ("due", 15, None)
    assert moved.fire_at == copy.due_at - timedelta(minutes=15)
