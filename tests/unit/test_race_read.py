"""Чистые правила `race/read.py`: какой заезд показывать на доске."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.race.read import pick_display_race


def _race(seq, status):
    return SimpleNamespace(seq=seq, status=status)


def test_active_contest_prefers_active_then_nearest_scheduled_then_last_finished():
    races = [_race(1, "finished"), _race(2, "active"), _race(3, "scheduled")]
    assert pick_display_race(races, "active").seq == 2
    races = [_race(1, "finished"), _race(2, "scheduled"), _race(3, "scheduled")]
    assert pick_display_race(races, "active").seq == 2
    assert pick_display_race([_race(1, "finished"), _race(2, "finished")], "active").seq == 2
    assert pick_display_race([], "active") is None


def test_cancelled_or_finished_contest_never_shows_a_scheduled_race():
    # Отмена 02.10: заезды 1–3 завершены, №4 остался scheduled — показывать №3.
    races = [
        _race(1, "finished"),
        _race(2, "finished"),
        _race(3, "finished"),
        _race(4, "scheduled"),
    ]
    assert pick_display_race(races, "cancelled").seq == 3
    assert pick_display_race(races, "finished").seq == 3
    # отменён до первого заезда — показывать нечего
    assert pick_display_race([_race(1, "scheduled")], "cancelled") is None
    # без статуса конкурса — прежнее правило (совместимость вызовов)
    assert pick_display_race(races).seq == 4
