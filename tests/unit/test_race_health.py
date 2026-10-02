"""Коды здоровья гонки (`/api/health/race`) — чистые правила без БД."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.race import health as h

TZ = ZoneInfo("Europe/Moscow")
# Понедельник 05.10.2026, 09:00 МСК — утро старта, закрытие в 03:45 прошло.
NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
S = date(2026, 10, 5)


def _snap(**kw):
    base = {
        "contest_status": "active",
        "contest_starts_on": S,
        "scheduled_at": datetime(2026, 10, 2, 15, 0, tzinfo=UTC),
        "last_success_at": NOW - timedelta(minutes=20),
        "last_error": None,
        "last_close_day": S - timedelta(days=1),
        "preliminary_closed": 0,
    }
    base.update(kw)
    return h.TenantRaceHealth(**base)


def test_healthy_active_contest_has_no_problems():
    assert h.health_problems(_snap(), now=NOW, tz=TZ) == []


def test_scheduled_contest_is_fine_until_its_start_day():
    tomorrow = _snap(contest_status="scheduled", contest_starts_on=S + timedelta(days=1))
    assert h.health_problems(tomorrow, now=NOW, tz=TZ) == []
    overdue = _snap(contest_status="scheduled", contest_starts_on=S)
    assert h.health_problems(overdue, now=NOW, tz=TZ) == ["activation_overdue"]
    # у запланированного остальные проверки не применяются: выгрузок ещё нет
    assert (
        h.health_problems(
            _snap(
                contest_status="scheduled",
                contest_starts_on=S + timedelta(days=2),
                last_success_at=None,
            ),
            now=NOW,
            tz=TZ,
        )
        == []
    )


def test_pull_stale_after_two_hours_and_error_code():
    assert (
        h.health_problems(
            _snap(last_success_at=NOW - timedelta(hours=1, minutes=59)), now=NOW, tz=TZ
        )
        == []
    )
    assert h.health_problems(
        _snap(last_success_at=NOW - timedelta(hours=2, minutes=1)), now=NOW, tz=TZ
    ) == ["pull_stale"]
    assert h.health_problems(_snap(last_success_at=None), now=NOW, tz=TZ) == ["pull_stale"]
    assert h.health_problems(_snap(last_error="iiko: 503"), now=NOW, tz=TZ) == ["pull_error"]


def test_close_stale_only_after_five_msk_and_only_if_contest_was_on_books():
    stale = _snap(last_close_day=S - timedelta(days=2))
    assert h.health_problems(stale, now=NOW, tz=TZ) == ["close_stale"]
    # 04:30 МСК — закрытие могло ещё не пройти, молчим
    early = datetime(2026, 10, 5, 1, 30, tzinfo=UTC)
    assert (
        h.health_problems(
            _snap(last_close_day=S - timedelta(days=2), last_success_at=early), now=early, tz=TZ
        )
        == []
    )
    # конкурс запланировали сегодня утром — прошлой ночью закрывать было нечего
    fresh = _snap(
        last_close_day=date(2026, 10, 1), scheduled_at=datetime(2026, 10, 5, 5, 0, tzinfo=UTC)
    )
    assert h.health_problems(fresh, now=NOW, tz=TZ) == []
    assert h.health_problems(_snap(last_close_day=None), now=NOW, tz=TZ) == ["close_stale"]


def test_preliminary_baseline_after_close_is_a_problem():
    assert h.health_problems(_snap(preliminary_closed=1), now=NOW, tz=TZ) == [
        "baseline_preliminary"
    ]


def test_problems_are_independent_and_ordered_as_declared():
    snap = _snap(
        last_success_at=None,
        last_error="boom",
        last_close_day=S - timedelta(days=3),
        preliminary_closed=2,
    )
    assert h.health_problems(snap, now=NOW, tz=TZ) == [
        "pull_stale",
        "pull_error",
        "close_stale",
        "baseline_preliminary",
    ]
