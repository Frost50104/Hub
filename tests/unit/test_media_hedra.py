"""Цена гуся: секунды по кускам, центы, границы месяца, лимит."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.media.hedra import pricing


def test_billed_seconds_ceil_per_chunk():
    assert pricing.billed_seconds([(0, 10.2), (20, 25)]) == 16
    assert pricing.billed_seconds([]) == 0
    assert pricing.billed_seconds([(0, 10.0)]) == 10
    assert pricing.billed_seconds([(5, 4)]) == 0


def test_estimate_cost_cents():
    assert pricing.estimate_cost_cents(60, "720p") == 300
    assert pricing.estimate_cost_cents(60, "540p") == 150
    assert pricing.estimate_cost_cents(60, "1080p") == 375
    assert pricing.estimate_cost_cents(1, "540p") == 3
    assert pricing.estimate_cost_cents(0, "720p") == 0
    with pytest.raises(ValueError, match="разрешение"):
        pricing.estimate_cost_cents(1, "4k")


def test_month_bounds_in_display_tz():
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)  # уже 1 ноября 01:30 МСК
    start, nxt = pricing.month_bounds(now, tz)
    assert (start.year, start.month, start.day, start.hour) == (2026, 11, 1, 0)
    assert (nxt.year, nxt.month, nxt.day) == (2026, 12, 1)
    assert start.tzinfo is not None
    start, nxt = pricing.month_bounds(datetime(2026, 12, 15, tzinfo=UTC), tz)
    assert (nxt.year, nxt.month) == (2027, 1)


def test_cap_allows():
    assert pricing.cap_allows(cap_minutes=30, used_seconds=1700, need_seconds=100)
    assert not pricing.cap_allows(cap_minutes=30, used_seconds=1700, need_seconds=101)
    assert pricing.cap_allows(cap_minutes=0, used_seconds=0, need_seconds=0)
