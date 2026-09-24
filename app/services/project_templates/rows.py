"""Чистые правила копирования проекта ↔ шаблона (0060).

Здесь только преобразование уже прочитанных строк — без сессии, без I/O, —
чтобы каждое правило держал юнит-тест: интеграционные тесты в CI не бегут.
Чтение и запись — `copy.py`.

Правила отбора (каждое — ответ на найденный отказ, см. план 21.09):
- архивные задачи не копируются;
- подзадача без родителя в наборе (родитель архивный или отброшен) — тоже:
  архивация помечает только саму задачу (`api/tasks.py::archive_task`), и
  без правила подзадача не нашла бы родителя в карте id;
- выполненная задача, у которой есть потомок по повтору, — прошедший шаг
  серии: иначе «еженедельная» с 20 закрытыми шагами дала бы в проекте 21
  одинаковую открытую задачу;
- наблюдатели — только `manual` и `assignee`: `creator` сделал бы автора
  шаблона наблюдателем каждой задачи каждого проекта, `mentioned` без
  скопированных комментариев смысла не имеет;
- уволенные (`shadow_users.deleted_at`) выпадают отовсюду, и их называют.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.services.taskdates import due_day, due_noon_utc, shift_days

COPIED_WATCHER_REASONS = frozenset({"manual", "assignee"})


@dataclass(frozen=True)
class SrcTask:
    id: UUID
    parent_task_id: UUID | None
    stage_id: UUID | None
    title: str
    description: str | None
    priority: str
    start_at: datetime | None
    due_at: datetime | None
    position: Any
    seq: int
    done: bool
    archived: bool
    has_recurrence_child: bool = False
    # Задано ли время у дат (0061). Дефолт — «день», как у строк до 0061.
    start_has_time: bool = False
    due_has_time: bool = False


@dataclass(frozen=True)
class Person:
    task_id: UUID
    employee_id: UUID
    alive: bool
    position: int = 0
    reason: str = ""


@dataclass
class Dropped:
    archived: int = 0
    orphan_subtasks: int = 0
    recurrence_steps: int = 0

    @property
    def total(self) -> int:
        return self.archived + self.orphan_subtasks + self.recurrence_steps


@dataclass
class Selection:
    """Отобранные задачи: сначала родители, потом подзадачи, внутри — по seq."""

    parents: list[SrcTask] = field(default_factory=list)
    children: list[SrcTask] = field(default_factory=list)
    dropped: Dropped = field(default_factory=Dropped)

    @property
    def ordered(self) -> list[SrcTask]:
        return self.parents + self.children

    @property
    def ids(self) -> set[UUID]:
        return {t.id for t in self.ordered}


def select_tasks(tasks: list[SrcTask]) -> Selection:
    sel = Selection()
    kept_parents: set[UUID] = set()
    for t in sorted(tasks, key=lambda x: x.seq):
        if t.parent_task_id is not None:
            continue
        if t.archived:
            sel.dropped.archived += 1
        elif t.done and t.has_recurrence_child:
            sel.dropped.recurrence_steps += 1
        else:
            sel.parents.append(t)
            kept_parents.add(t.id)
    for t in sorted(tasks, key=lambda x: x.seq):
        if t.parent_task_id is None:
            continue
        if t.archived:
            sel.dropped.archived += 1
        elif t.parent_task_id not in kept_parents:
            sel.dropped.orphan_subtasks += 1
        elif t.done and t.has_recurrence_child:
            sel.dropped.recurrence_steps += 1
        else:
            sel.children.append(t)
    return sel


def seq_map(sel: Selection, first: int) -> dict[UUID, int]:
    """Номера 1..N (от `first`) в порядке ИСХОДНЫХ номеров, как у разноски
    `split_project_by_labels`: «KEY-3» остаётся раньше «KEY-7»."""
    ordered = sorted(sel.ordered, key=lambda t: t.seq)
    return {t.id: first + i for i, t in enumerate(ordered)}


def shifted_due(due_at: datetime | None, days: int, has_time: bool = False) -> datetime | None:
    """Сдвиг срока на `days` календарных дней.

    Без времени срок — календарный день: сдвиг дня и снова полдень display tz.
    Со временем (0061) — тот же час в новом дне (`shift_days`, DST-безопасно):
    полдень здесь молча снимал бы «к 15:00» у каждой задачи проекта по шаблону.
    """
    if due_at is None:
        return None
    if days == 0:
        return due_at
    if has_time:
        return shift_days(due_at, days)
    return due_noon_utc(date.fromordinal(due_day(due_at).toordinal() + days))


def shifted_start(start_at: datetime | None, days: int) -> datetime | None:
    return None if start_at is None else shift_days(start_at, days)


def shifted_date_value(value: Any, days: int) -> Any:
    """Значение кастом-поля типа date (`YYYY-MM-DD`) — тем же сдвигом."""
    if days == 0 or not isinstance(value, str):
        return value
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return value
    return date.fromordinal(d.toordinal() + days).isoformat()


def suggested_anchor(sel: Selection, today: date) -> date:
    """Точка отсчёта нового шаблона: самый ранний день начала или срока.

    Не дата создания проекта: у перенесённых из WEEEK это день импорта.
    """
    days = [due_day(t.due_at) for t in sel.ordered if t.due_at is not None]
    days += [due_day(t.start_at) for t in sel.ordered if t.start_at is not None]
    return min(days) if days else today


def date_range(sel: Selection, days: int) -> tuple[date | None, date | None]:
    """Первый и последний срок ПОСЛЕ сдвига — для предпросмотра."""
    dues = [
        shifted_due(t.due_at, days, t.due_has_time)
        for t in sel.ordered
        if t.due_at is not None
    ]
    if not dues:
        return None, None
    ds = [due_day(d) for d in dues if d is not None]
    return min(ds), max(ds)


def overdue_after_shift(sel: Selection, days: int, today: date) -> int:
    """Сколько задач сразу окажутся просроченными (сроки до точки отсчёта)."""
    n = 0
    for t in sel.ordered:
        d = shifted_due(t.due_at, days, t.due_has_time)
        if d is not None and due_day(d) < today:
            n += 1
    return n


def due_within(sel: Selection, days: int, today: date, horizon_days: int = 1) -> int:
    """Сколько задач получат срок в ближайшие `horizon_days` суток — столько
    напоминаний «скоро срок» придёт каждому исполнителю и наблюдателю."""
    n = 0
    for t in sel.ordered:
        d = shifted_due(t.due_at, days, t.due_has_time)
        if d is None:
            continue
        delta = (due_day(d) - today).days
        if 0 <= delta <= horizon_days:
            n += 1
    return n


def live_assignees(assignees: list[Person], task_ids: set[UUID]) -> list[Person]:
    return [a for a in assignees if a.task_id in task_ids and a.alive]


def watchers_to_copy(
    watchers: list[Person], assignees: list[Person], task_ids: set[UUID]
) -> list[tuple[UUID, UUID, str]]:
    """(task_id, employee_id, reason): ручные и «исполнитель» — живые; плюс
    строка `assignee` каждому скопированному исполнителю (как в повторе).
    Порядок стабилен, дубли по (task, employee) отброшены — первая причина."""
    out: dict[tuple[UUID, UUID], str] = {}
    for w in watchers:
        if w.task_id in task_ids and w.alive and w.reason in COPIED_WATCHER_REASONS:
            out.setdefault((w.task_id, w.employee_id), w.reason)
    for a in live_assignees(assignees, task_ids):
        out.setdefault((a.task_id, a.employee_id), "assignee")
    return [(t, e, r) for (t, e), r in out.items()]


def dropped_people(
    assignees: list[Person], watchers: list[Person], task_ids: set[UUID]
) -> Counter[UUID]:
    """Уволенные, выпавшие из исполнителей и наблюдателей: id → число задач."""
    seen: set[tuple[UUID, UUID]] = set()
    counter: Counter[UUID] = Counter()
    for p in [*assignees, *watchers]:
        if p.task_id not in task_ids or p.alive:
            continue
        if isinstance(p.reason, str) and p.reason and p.reason not in COPIED_WATCHER_REASONS:
            continue
        key = (p.task_id, p.employee_id)
        if key in seen:
            continue
        seen.add(key)
        counter[p.employee_id] += 1
    return counter


def summary_counts(
    assignees: list[Person], task_ids: set[UUID], *, exclude: UUID | None
) -> dict[UUID, int]:
    """Сводное уведомление: сколько задач (с подзадачами) у каждого живого
    исполнителя, кроме того, кто создаёт проект."""
    counter: Counter[UUID] = Counter()
    for a in live_assignees(assignees, task_ids):
        if a.employee_id != exclude:
            counter[a.employee_id] += 1
    return dict(counter)


def members_to_copy(
    members: list[tuple[UUID, str, bool]], *, exclude: set[UUID]
) -> list[tuple[UUID, str]]:
    """Состав роль в роль: только живые и не из `exclude`.

    `exclude` при создании проекта — создающий (он уже owner), при сохранении
    шаблона — сохраняющий (решение владельца «автор — только если добавлен
    явно»; иначе автор становился бы owner каждого проекта из шаблона).
    """
    return [(e, r) for e, r, alive in members if alive and e not in exclude]
