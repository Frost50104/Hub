"""Правила копирования проекта ↔ шаблона (0060) — чистые функции `rows.py`.

Интеграционные тесты в CI не бегут, поэтому каждое правило отбора, найденное
при разборе плана, держит юнит-тест здесь.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.project_templates import rows
from app.services.ru_plural import ru_plural


def _t(seq: int, **kw) -> rows.SrcTask:
    base = {
        "id": uuid.uuid4(),
        "parent_task_id": None,
        "stage_id": None,
        "title": f"T{seq}",
        "description": None,
        "priority": "medium",
        "start_at": None,
        "due_at": None,
        "position": seq,
        "seq": seq,
        "done": False,
        "archived": False,
    }
    base.update(kw)
    return rows.SrcTask(**base)


def test_archived_and_orphan_subtasks_are_dropped():
    # Архивация помечает только саму задачу: подзадачи архивного родителя
    # остаются живыми (на проде таких 3) и без правила не нашли бы родителя.
    parent_archived = _t(1, archived=True)
    orphan = _t(2, parent_task_id=parent_archived.id)
    alive = _t(3)
    child = _t(4, parent_task_id=alive.id)
    sel = rows.select_tasks([child, orphan, alive, parent_archived])
    assert [t.id for t in sel.parents] == [alive.id]
    assert [t.id for t in sel.children] == [child.id]
    assert sel.dropped.archived == 1
    assert sel.dropped.orphan_subtasks == 1


def test_done_recurrence_steps_are_dropped_but_live_head_stays():
    # Шаги серии повтора — выполненные задачи с потомком: иначе 20 закрытых
    # шагов «еженедельной» дали бы 21 одинаковую открытую задачу.
    step1 = _t(1, done=True, has_recurrence_child=True)
    step2 = _t(2, done=True, has_recurrence_child=True)
    head = _t(3)
    done_plain = _t(4, done=True)
    sel = rows.select_tasks([step1, step2, head, done_plain])
    assert {t.id for t in sel.parents} == {head.id, done_plain.id}
    assert sel.dropped.recurrence_steps == 2


def test_subtask_of_dropped_recurrence_step_is_orphan():
    step = _t(1, done=True, has_recurrence_child=True)
    sub = _t(2, parent_task_id=step.id)
    sel = rows.select_tasks([step, sub])
    assert sel.ordered == []
    assert sel.dropped.orphan_subtasks == 1


def test_seq_map_keeps_source_order_from_first():
    a, b, c = _t(7), _t(3), _t(5, parent_task_id=None)
    sub = _t(4, parent_task_id=b.id)
    sel = rows.select_tasks([a, b, c, sub])
    m = rows.seq_map(sel, first=1)
    assert [m[x.id] for x in (b, sub, c, a)] == [1, 2, 3, 4]


def test_due_shift_is_calendar_day_at_noon():
    due = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)  # 12:00 МСК
    shifted = rows.shifted_due(due, 30)
    assert shifted == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert rows.shifted_due(None, 5) is None
    assert rows.shifted_due(due, 0) is due


def test_start_shift_keeps_local_hour_across_dst(monkeypatch):
    # Москва без перехода на летнее время; правило обязано держаться и в
    # поясе с переходом — `timedelta` в UTC сдвинул бы час.
    berlin = ZoneInfo("Europe/Berlin")
    monkeypatch.setattr("app.services.taskdates.display_tz", lambda: berlin)
    start = datetime(2026, 3, 20, 10, 0, tzinfo=berlin)  # до перехода
    moved = rows.shifted_start(start.astimezone(UTC), 14)  # после перехода
    assert moved is not None
    local = moved.astimezone(berlin)
    assert (local.date(), local.hour) == (date(2026, 4, 3), 10)


def test_date_field_value_shift():
    assert rows.shifted_date_value("2026-09-01", 3) == "2026-09-04"
    assert rows.shifted_date_value("2026-09-01", 0) == "2026-09-01"
    assert rows.shifted_date_value("не дата", 3) == "не дата"
    assert rows.shifted_date_value(None, 3) is None


def test_suggested_anchor_is_earliest_date_or_today():
    early = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    later = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    sel = rows.select_tasks([_t(1, due_at=later), _t(2, start_at=early)])
    assert rows.suggested_anchor(sel, date(2026, 9, 21)) == date(2026, 8, 3)
    assert rows.suggested_anchor(rows.select_tasks([_t(1)]), date(2026, 9, 21)) == date(
        2026, 9, 21
    )


def test_overdue_and_due_soon_counts_after_shift():
    today = date(2026, 9, 21)
    anchor_due = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    before_anchor = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
    sel = rows.select_tasks([_t(1, due_at=anchor_due), _t(2, due_at=before_anchor)])
    shift = (today - date(2026, 9, 1)).days  # старт сегодня
    assert rows.overdue_after_shift(sel, shift, today) == 1
    assert rows.due_within(sel, shift, today) == 1


def test_watchers_copy_only_manual_and_assignee_alive():
    t = uuid.uuid4()
    author, manual, dead, assignee = (uuid.uuid4() for _ in range(4))
    watchers = [
        rows.Person(task_id=t, employee_id=author, alive=True, reason="creator"),
        rows.Person(task_id=t, employee_id=manual, alive=True, reason="manual"),
        rows.Person(task_id=t, employee_id=dead, alive=False, reason="manual"),
    ]
    assignees = [rows.Person(task_id=t, employee_id=assignee, alive=True)]
    got = rows.watchers_to_copy(watchers, assignees, {t})
    assert set(got) == {(t, manual, "manual"), (t, assignee, "assignee")}


def test_dropped_people_and_summary():
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    alive, dead, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assignees = [
        rows.Person(task_id=t1, employee_id=alive, alive=True),
        rows.Person(task_id=t2, employee_id=alive, alive=True),
        rows.Person(task_id=t1, employee_id=dead, alive=False),
        rows.Person(task_id=t2, employee_id=actor, alive=True),
    ]
    assert rows.dropped_people(assignees, [], {t1, t2}) == {dead: 1}
    # Создающий проект сводку себе не шлёт.
    assert rows.summary_counts(assignees, {t1, t2}, exclude=actor) == {alive: 2}


def test_members_exclude_actor_and_dead():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    members = [(a, "owner", True), (b, "editor", True), (c, "viewer", False)]
    assert rows.members_to_copy(members, exclude={a}) == [(b, "editor")]


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "1 задача"), (2, "2 задачи"), (5, "5 задач"), (11, "11 задач"), (21, "21 задача"),
     (112, "112 задач"), (104, "104 задачи")],
)
def test_ru_plural(n, expected):
    assert ru_plural(n, "задача", "задачи", "задач") == expected
