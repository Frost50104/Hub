"""timefmt — человекочитаемые даты в локальном времени сети (не UTC).

QA-0821 #27: «Вы назначены на смену 30.08 08:00–16:00 UTC» при 10:00–18:00
в интерфейсе. Все timestamptz в БД — UTC, людям показываем
settings.display_timezone (default Europe/Moscow).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import get_settings
from app.services.timefmt import fmt_date, fmt_dt, fmt_range, to_display


def test_range_same_day_in_moscow() -> None:
    start = datetime(2026, 8, 30, 7, 0, tzinfo=UTC)
    end = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
    assert fmt_range(start, end) == "30.08 10:00–18:00"


def test_range_crossing_midnight_shows_both_dates() -> None:
    start = datetime(2026, 8, 30, 19, 0, tzinfo=UTC)  # 22:00 МСК
    end = datetime(2026, 8, 31, 3, 0, tzinfo=UTC)  # 06:00 МСК следующего дня
    assert fmt_range(start, end) == "30.08 22:00–31.08 06:00"


def test_naive_datetime_is_treated_as_utc() -> None:
    naive = datetime(2026, 8, 30, 21, 30)  # джобы пишут naive UTC
    assert fmt_dt(naive, "%d.%m в %H:%M") == "31.08 в 00:30"
    assert to_display(naive).tzinfo is not None


def test_date_uses_display_timezone_day() -> None:
    # 23:30 UTC 30.08 — это уже 31.08 по Москве: дедлайн «до 31.08.2026».
    assert fmt_date(datetime(2026, 8, 30, 23, 30, tzinfo=UTC)) == "31.08.2026"


def test_display_timezone_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNARIS_HUB_DISPLAY_TIMEZONE", "Asia/Yekaterinburg")
    get_settings.cache_clear()
    try:
        assert fmt_dt(datetime(2026, 8, 30, 7, 0, tzinfo=UTC), "%H:%M") == "12:00"
    finally:
        get_settings.cache_clear()
