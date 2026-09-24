"""Время у старта и срока задачи (0061) — чистые правила.

Интеграционные тесты в CI не бегут, поэтому правило пары (мгновение, флаг),
сохранение часа на копиях и тексты держат юнит-тесты здесь.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.api.tasks_import import _parse_due
from app.services import taskdates as td
from app.services.assistant.tools import fmt_due as assistant_fmt_due
from app.services.assistant.tools import keep_task_time
from app.services.project_templates import rows
from app.services.task_recurrence import _copy_due, _shifted
from app.services.timefmt import fmt_due, fmt_when

MSK = ZoneInfo("Europe/Moscow")


def _msk(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=MSK).astimezone(UTC)


# ─── Правило пары для PATCH/создания ────────────────────────────────────────


def _resolve(fields: set[str], at=None, flag=None):
    return td.resolve_date_patch(
        fields, at_field="due_at", flag_field="due_has_time", new_at=at, new_flag=flag
    )


def test_untouched_date_returns_none() -> None:
    assert _resolve({"title"}) is None


def test_date_without_flag_is_a_day() -> None:
    # Так пишут старые PWA-бандлы, CSV и ассистент: они знают только дни.
    at = _msk(2026, 9, 30, 15)
    assert _resolve({"due_at"}, at=at) == (at, False)


def test_date_with_flag_is_a_moment() -> None:
    at = _msk(2026, 9, 30, 15)
    assert _resolve({"due_at", "due_has_time"}, at=at, flag=True) == (at, True)


def test_noon_time_is_still_a_time() -> None:
    # 12:00 даёт то же мгновение, что день без времени — флаг обязан сохраниться.
    noon = td.due_noon_utc(date(2026, 9, 30))
    assert _resolve({"due_at", "due_has_time"}, at=noon, flag=True) == (noon, True)


def test_cleared_date_drops_flag() -> None:
    assert _resolve({"due_at", "due_has_time"}, at=None, flag=True) == (None, False)


def test_flag_without_date_is_an_error() -> None:
    with pytest.raises(td.DatePatchError):
        _resolve({"due_has_time"}, flag=True)


# ─── Местное время ──────────────────────────────────────────────────────────


def test_local_time_and_back() -> None:
    moment = _msk(2026, 9, 30, 15, 30)
    assert td.local_time_of(moment) == time(15, 30)
    assert td.at_local(date(2026, 10, 2), time(15, 30)) == _msk(2026, 10, 2, 15, 30)


def test_at_local_keeps_hour_across_dst(monkeypatch: pytest.MonkeyPatch) -> None:
    berlin = ZoneInfo("Europe/Berlin")
    monkeypatch.setattr("app.services.taskdates.display_tz", lambda: berlin)
    before = datetime(2026, 3, 20, 15, 0, tzinfo=berlin).astimezone(UTC)
    after = td.at_local(date(2026, 4, 3), td.local_time_of(before))
    assert after.astimezone(berlin).hour == 15


# ─── Тексты ─────────────────────────────────────────────────────────────────


def test_fmt_due_prints_hour_only_when_chosen() -> None:
    noon = td.due_noon_utc(date(2026, 9, 30))
    # До 0061 «Скоро дедлайн» писал «в 12:00» у любого срока без времени.
    assert fmt_due(noon, False) == "30.09"
    assert fmt_due(_msk(2026, 9, 30, 15), True) == "30.09 в 15:00"


def test_fmt_when_relative_days() -> None:
    now = _msk(2026, 9, 30, 10)
    assert fmt_when(_msk(2026, 9, 30, 15), True, now) == "сегодня в 15:00"
    assert fmt_when(td.due_noon_utc(date(2026, 10, 1)), False, now) == "завтра"
    assert fmt_when(_msk(2026, 10, 5, 9), True, now) == "05.10 в 09:00"


def test_assistant_fmt_due_adds_hour() -> None:
    assert assistant_fmt_due(_msk(2026, 8, 22, 15), True) == "22 августа, суббота, 15:00"
    assert assistant_fmt_due(td.due_noon_utc(date(2026, 8, 22))) == "22 августа, суббота"


# ─── Копии: повтор, шаблон ──────────────────────────────────────────────────


def test_recurrence_copy_keeps_hour() -> None:
    timed = SimpleNamespace(due_at=_msk(2026, 9, 30, 15), due_has_time=True)
    assert _copy_due(timed, date(2026, 10, 1)) == _msk(2026, 10, 1, 15)
    day = SimpleNamespace(due_at=td.due_noon_utc(date(2026, 9, 30)), due_has_time=False)
    assert _copy_due(day, date(2026, 10, 1)) == td.due_noon_utc(date(2026, 10, 1))
    assert _copy_due(timed, None) is None


def test_recurrence_start_shift_keeps_hour() -> None:
    start = _msk(2026, 9, 30, 9)
    assert _shifted(start, 7) == _msk(2026, 10, 7, 9)
    assert _shifted(None, 7) is None


def test_template_shift_keeps_hour_when_timed() -> None:
    due = _msk(2026, 9, 1, 15)
    assert rows.shifted_due(due, 30, True) == _msk(2026, 10, 1, 15)
    # Без времени — по-прежнему полдень нового дня.
    assert rows.shifted_due(due, 30) == td.due_noon_utc(date(2026, 10, 1))


def test_template_preview_counts_timed_tasks_by_day() -> None:
    t = rows.SrcTask(
        id=uuid.uuid4(), parent_task_id=None, stage_id=None, title="T", description=None,
        priority="medium", start_at=None, due_at=_msk(2026, 9, 1, 23, 30), position=1,
        seq=1, done=False, archived=False, due_has_time=True,
    )
    sel = rows.select_tasks([t])
    assert rows.date_range(sel, 2) == (date(2026, 9, 3), date(2026, 9, 3))


# ─── CSV ────────────────────────────────────────────────────────────────────


def test_csv_due_day_and_time() -> None:
    assert _parse_due("21.08.2026") == (td.due_noon_utc(date(2026, 8, 21)), False)
    assert _parse_due("2026-08-21") == (td.due_noon_utc(date(2026, 8, 21)), False)
    assert _parse_due("21.08.2026 15:30") == (_msk(2026, 8, 21, 15, 30), True)
    # Наивное ISO со временем — по display tz, а не UTC (так было до 0061).
    assert _parse_due("2026-08-21T15:30") == (_msk(2026, 8, 21, 15, 30), True)
    assert _parse_due("2026-08-21T12:30:00+00:00") == (
        datetime(2026, 8, 21, 12, 30, tzinfo=UTC),
        True,
    )
    assert _parse_due("вчера") is None
    assert _parse_due("  ") is None


# ─── Ассистент: перенос дня без потери часа ─────────────────────────────────


def test_assistant_keeps_task_hour_per_task() -> None:
    new_day = td.due_noon_utc(date(2026, 10, 2))
    timed = SimpleNamespace(due_at=_msk(2026, 9, 30, 15), due_has_time=True)
    day = SimpleNamespace(due_at=td.due_noon_utc(date(2026, 9, 30)), due_has_time=False)
    assert keep_task_time(timed, {"due_at": new_day}) == {
        "due_at": _msk(2026, 10, 2, 15),
        "due_has_time": True,
    }
    assert keep_task_time(day, {"due_at": new_day}) == {"due_at": new_day}
    # Снятие срока не трогаем.
    assert keep_task_time(timed, {"due_at": None}) == {"due_at": None}
