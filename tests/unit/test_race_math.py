"""Арифметика «Гусиной гонки» (`app/services/race/math.py`).

Интеграционные тесты в CI не бегут, а здесь ровно тот класс ошибок, который
всплывает через неделю живой гонки: половинки клеток у двух точек, штраф за
пропущенную гонку, «рекорд» в первый день, догон пропущенной ночи.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.race import math as m

L1 = UUID("00000000-0000-0000-0000-00000000000a")
L2 = UUID("00000000-0000-0000-0000-00000000000b")


def _row(name: str, cells: int, pct: float | None = None, *, avg=None, league=None, nb=False):
    return m.RankRow(
        store_id=uuid4(),
        name=name,
        cells=cells,
        pct=pct,
        avg=avg,
        needs_baseline=nb,
        league_id=league,
    )


# ─── клетки и проценты ──────────────────────────────────────────────────────


def test_cells_scale_and_clamp():
    assert m.compute_cells(2.0, 2.0) == (100, False)
    assert m.compute_cells(3.0, 2.0) == (150, False)
    assert m.compute_cells(8.0, 2.0) == (400, False)
    assert m.compute_cells(9.0, 2.0) == (400, False), "потолок 400"
    assert m.compute_cells(0.0, 2.0) == (0, False), "ниже старта возможно, пол — 0"
    assert m.compute_cells(1.0, 2.0) == (50, False)


def test_cells_round_half_up_not_bankers():
    # 100 × 2.41 / 2.0 = 120.5 → 121 у любой точки, а не 120/122 по чётности.
    assert m.compute_cells(2.41, 2.0)[0] == 121
    assert m.compute_cells(2.43, 2.0)[0] == 122


def test_missing_or_zero_base_parks_at_start_with_flag():
    assert m.compute_cells(2.5, None) == (100, True)
    assert m.compute_cells(2.5, 0) == (100, True)
    assert m.compute_cells(None, 2.0) == (100, True), "нет чеков — нет средней"
    assert m.compute_pct(2.5, None) is None
    assert m.compute_pct(None, 2.0) is None


def test_pct_one_decimal_with_sign():
    assert m.compute_pct(3.0, 2.0) == 50.0
    assert m.compute_pct(2.23, 2.0) == 11.5
    assert m.compute_pct(1.5, 2.0) == -25.0


def test_avg_needs_receipts():
    assert m.compute_avg(10.0, 0) is None
    assert m.compute_avg(10.0, 4) == 2.5


# ─── места ──────────────────────────────────────────────────────────────────


def test_rank_orders_by_cells_then_pct_then_name_and_parks_no_base():
    rows = [
        _row("Б", 150, 50.0),
        _row("А", 150, 50.0),
        _row("В", 200, 100.0),
        _row("Г", 100, 0.0, nb=True),
        _row("Д", 150, 50.4),
    ]
    out = m.rank(rows)
    assert [r.name for r in out] == ["В", "Д", "А", "Б", "Г"]
    assert [r.place for r in out] == [1, 2, 3, 4, None]
    assert out[-1].needs_baseline and out[-1].place is None


def test_rank_assigns_places_in_league_independently():
    rows = [
        _row("А", 300, league=L1),
        _row("Б", 250, league=L2),
        _row("В", 200, league=L1),
        _row("Г", 150),  # вне лиг
    ]
    out = m.rank(rows)
    by = {r.name: r for r in out}
    assert (by["А"].place, by["А"].place_in_league) == (1, 1)
    assert (by["Б"].place, by["Б"].place_in_league) == (2, 1)
    assert (by["В"].place, by["В"].place_in_league) == (3, 2)
    assert (by["Г"].place, by["Г"].place_in_league) == (4, None)


# ─── общий зачёт ────────────────────────────────────────────────────────────


def _participants(*names, leagues=None):
    ids = {n: uuid4() for n in names}
    leagues = leagues or {}
    return ids, [m.ParticipantRow(ids[n], n, leagues.get(n)) for n in names]


def _result(ids, name, place, pct, *, league=None, pil=None):
    return m.ResultRow(ids[name], place, pil, pct, league)


def test_standings_sum_places_lower_is_better():
    ids, parts = _participants("А", "Б", "В")
    r1 = [_result(ids, "А", 1, 50), _result(ids, "Б", 2, 30), _result(ids, "В", 3, 10)]
    r2 = [_result(ids, "А", 2, 20), _result(ids, "Б", 1, 60), _result(ids, "В", 3, 5)]
    out = m.standings([r1, r2], parts)
    # А и Б по 3 очка; выше Б — у неё сумма процентов 90 против 70.
    assert [(s.name, s.points, s.place) for s in out] == [("Б", 3, 1), ("А", 3, 2), ("В", 6, 3)]
    assert out[0].pct_sum == 90.0 and out[1].pct_sum == 70.0
    assert all(s.races_counted == 2 and s.missed_races == 0 for s in out)


def test_standings_tie_broken_by_pct_sum():
    ids, parts = _participants("А", "Б")
    r1 = [_result(ids, "А", 1, 10), _result(ids, "Б", 2, 40)]
    r2 = [_result(ids, "А", 2, 10), _result(ids, "Б", 1, 5)]
    out = m.standings([r1, r2], parts)
    assert [s.name for s in out] == ["Б", "А"], "при равной сумме мест выше тот, у кого больше %"


def test_standings_missed_race_costs_n_plus_one():
    ids, parts = _participants("А", "Б", "В")
    r1 = [_result(ids, "А", 1, 50), _result(ids, "Б", 2, 30)]  # В пропустила
    r2 = [_result(ids, "А", 2, 5), _result(ids, "Б", 3, 1), _result(ids, "В", 1, 90)]
    out = m.standings([r1, r2], parts)
    by = {s.name: s for s in out}
    assert by["В"].points == 3 + 1 and by["В"].missed_races == 1 and by["В"].races_counted == 1
    assert by["А"].points == 3 and by["А"].missed_races == 0
    assert [s.name for s in out] == ["А", "В", "Б"]


def test_standings_no_base_in_a_race_counts_as_missed():
    ids, parts = _participants("А", "Б")
    r1 = [_result(ids, "А", 1, 50), _result(ids, "Б", None, None)]
    out = m.standings([r1], parts)
    by = {s.name: s for s in out}
    assert by["Б"].points == 2 and by["Б"].missed_races == 1


def test_standings_empty_until_first_race_finishes():
    _, parts = _participants("А")
    assert m.standings([], parts) == []


def test_standings_league_places_use_league_points():
    ids, parts = _participants("А", "Б", "В", leagues={"А": L1, "Б": L1, "В": L2})
    r1 = [
        _result(ids, "В", 1, 90, league=L2, pil=1),
        _result(ids, "Б", 2, 40, league=L1, pil=1),
        _result(ids, "А", 3, 10, league=L1, pil=2),
    ]
    out = m.standings([r1], parts)
    by = {s.name: s for s in out}
    assert by["Б"].place_in_league == 1 and by["А"].place_in_league == 2
    assert by["В"].place_in_league == 1 and by["В"].points_in_league == 1


# ─── динамика и рекорд ──────────────────────────────────────────────────────


def test_dynamics_threshold_is_one_cell():
    assert m.dynamics(120, None) is None
    assert m.dynamics(121, 120) == "up"
    assert m.dynamics(120, 120) == "flat"
    assert m.dynamics(119, 120) == "down"


def test_record_never_on_first_day_and_only_above_start():
    assert m.is_record(150, None) is False, "первый день заезда — нет прежнего максимума"
    assert m.is_record(100, 90) is False, "на стартовой линии рекорда нет"
    assert m.is_record(101, 100) is True
    assert m.is_record(150, 150) is False
    assert m.is_record(151, 150) is True


# ─── даты ───────────────────────────────────────────────────────────────────


def test_generate_races_four_weeks_by_seven_and_by_fourteen():
    start = date(2026, 9, 21)  # понедельник
    r7 = m.generate_races(start, 4, 7)
    assert [(r.seq, r.starts_on, r.ends_on) for r in r7] == [
        (1, date(2026, 9, 21), date(2026, 9, 27)),
        (2, date(2026, 9, 28), date(2026, 10, 4)),
        (3, date(2026, 10, 5), date(2026, 10, 11)),
        (4, date(2026, 10, 12), date(2026, 10, 18)),
    ]
    assert r7[-1].ends_on == m.contest_ends_on(start, 4)
    r14 = m.generate_races(start, 4, 14)
    assert len(r14) == 2 and r14[1].ends_on == date(2026, 10, 18)


def test_generate_races_rejects_non_divisible():
    with pytest.raises(ValueError):
        m.generate_races(date(2026, 9, 21), 3, 14)


def test_retro_period_ends_the_day_before_start():
    assert m.retro_period(date(2026, 9, 21), 28) == (date(2026, 8, 24), date(2026, 9, 20))


def test_pending_snapshot_days_catches_up_and_stops_at_race_end():
    start, end = date(2026, 9, 21), date(2026, 9, 27)
    assert m.pending_snapshot_days(start, end, None, date(2026, 9, 21)) == [date(2026, 9, 21)]
    # две пропущенные ночи
    assert m.pending_snapshot_days(start, end, date(2026, 9, 22), date(2026, 9, 25)) == [
        date(2026, 9, 23),
        date(2026, 9, 24),
        date(2026, 9, 25),
    ]
    # закрытие после конца гонки не выходит за ends_on
    assert m.pending_snapshot_days(start, end, date(2026, 9, 26), date(2026, 9, 30)) == [
        date(2026, 9, 27)
    ]
    assert m.pending_snapshot_days(start, end, date(2026, 9, 27), date(2026, 9, 30)) == []
    # до старта гонки — нечего снимать
    assert m.pending_snapshot_days(start, end, None, date(2026, 9, 20)) == []


def test_chunk_period_windows_of_fourteen_days():
    chunks = m.chunk_period(date(2026, 8, 24), date(2026, 9, 20), 14)
    assert chunks == [
        (date(2026, 8, 24), date(2026, 9, 6)),
        (date(2026, 9, 7), date(2026, 9, 20)),
    ]
    one = (date(2026, 9, 1), date(2026, 9, 1))
    assert m.chunk_period(*one) == [one]
    assert m.chunk_period(date(2026, 9, 2), date(2026, 9, 1)) == []


# ─── ранний старт заезда ────────────────────────────────────────────────────


def test_early_start_day_not_before_the_day_after_previous_end():
    d = date(2026, 9, 21)
    sched = d + timedelta(days=5)
    # в день досрочного закрытия предыдущего — только «завтра»
    assert m.early_start_day(d, d, sched) == d + timedelta(days=1)
    # позже — «сегодня»
    assert m.early_start_day(d + timedelta(days=2), d, sched) == d + timedelta(days=2)
    # расписание и так начинает не позже — начинать раньше нечего
    assert m.early_start_day(sched, d, sched) is None
    assert m.early_start_day(d, d, d + timedelta(days=1)) is None


def test_early_start_candidate_needs_no_active_race_and_finished_predecessor():
    d = date(2026, 9, 21)
    r1 = SimpleNamespace(id=1, seq=1, status="finished", starts_on=d - timedelta(days=6), ends_on=d)
    r2 = SimpleNamespace(
        id=2,
        seq=2,
        status="scheduled",
        starts_on=d + timedelta(days=5),
        ends_on=d + timedelta(days=11),
    )
    r3 = SimpleNamespace(
        id=3,
        seq=3,
        status="scheduled",
        starts_on=d + timedelta(days=12),
        ends_on=d + timedelta(days=18),
    )
    assert m.early_start_candidate([r3, r2, r1], d) == (r2, d + timedelta(days=1))
    assert m.early_start_candidate([r1, r2, r3], d + timedelta(days=5)) is None, "и так стартует"
    r1_active = SimpleNamespace(**{**vars(r1), "status": "active"})
    assert m.early_start_candidate([r1_active, r2, r3], d) is None, "активный есть"
    assert m.early_start_candidate([r2, r3], d) is None, "предшественника нет"
    r1_sched = SimpleNamespace(**{**vars(r1), "status": "scheduled"})
    assert m.early_start_candidate([r1_sched, r2], d) is None, "предшественник не завершён"
    assert m.early_start_candidate([r1], d) is None
