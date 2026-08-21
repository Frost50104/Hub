"""taskdates — срок задачи как календарный день display tz (ОС тестировщика 2026-08:
«срок сегодня → просрочено на 1 день после полудня»)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.config import get_settings
from app.services import taskdates as td


def test_day_boundaries_in_moscow() -> None:
    assert td.day_start_utc(date(2026, 8, 21)) == datetime(2026, 8, 20, 21, 0, tzinfo=UTC)
    assert td.due_noon_utc(date(2026, 8, 21)) == datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    now = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)  # 18:00 МСК
    assert td.display_today(now) == date(2026, 8, 21)
    assert td.start_of_today_utc(now) == datetime(2026, 8, 20, 21, 0, tzinfo=UTC)
    assert td.start_of_tomorrow_utc(now) == datetime(2026, 8, 21, 21, 0, tzinfo=UTC)


def test_due_today_is_not_overdue_until_day_ends() -> None:
    due = td.due_noon_utc(date(2026, 8, 20))  # 12:00 МСК 20.08
    evening = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)  # 23:00 МСК того же дня
    after_midnight = datetime(2026, 8, 20, 21, 30, tzinfo=UTC)  # 00:30 МСК 21.08
    assert td.is_overdue(due, "todo", now=evening) is False
    assert td.overdue_days(due, now=evening) == 0
    assert td.is_overdue(due, "todo", now=after_midnight) is True
    assert td.overdue_days(due, now=after_midnight) == 1
    assert td.overdue_days(due, now=datetime(2026, 8, 23, 12, 0, tzinfo=UTC)) == 3
    assert td.is_overdue(due, "done", now=datetime(2026, 8, 23, 12, 0, tzinfo=UTC)) is False
    assert td.is_overdue(None, "todo") is False


def test_naive_datetimes_are_utc() -> None:
    naive_now = datetime(2026, 8, 20, 21, 30)
    assert td.display_today(naive_now) == date(2026, 8, 21)


def test_display_timezone_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNARIS_HUB_DISPLAY_TIMEZONE", "Asia/Yekaterinburg")
    get_settings.cache_clear()
    try:
        assert td.day_start_utc(date(2026, 8, 21)) == datetime(2026, 8, 20, 19, 0, tzinfo=UTC)
    finally:
        get_settings.cache_clear()
