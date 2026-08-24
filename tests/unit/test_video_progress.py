"""Юнит-тесты video_progress: merge интервалов + покрытие ≥90%."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.schemas.course import VideoProgressBody
from app.services import video_progress as vp
from app.services.video_progress import (
    DURATION_TOLERANCE,
    MAX_INTERVALS,
    WATCH_THRESHOLD,
    coverage,
    is_watched,
    merge_intervals,
    normalize_duration,
    resolve_duration,
)


class TestMergeIntervals:
    def test_empty(self):
        assert merge_intervals([], []) == []

    def test_disjoint_sorted(self):
        assert merge_intervals([[0, 10]], [[20, 30]]) == [[0, 10], [20, 30]]

    def test_overlap_merged(self):
        assert merge_intervals([[0, 10]], [[5, 15]]) == [[0, 15]]

    def test_small_gap_closed(self):
        # Щели < 0.5с смыкаются (пинги раз в 15с неточны на границах).
        assert merge_intervals([[0, 10.0]], [[10.4, 20]]) == [[0, 20]]

    def test_real_gap_kept(self):
        assert merge_intervals([[0, 10.0]], [[10.6, 20]]) == [[0, 10.0], [10.6, 20]]

    def test_unsorted_input(self):
        assert merge_intervals([[20, 30]], [[0, 10], [5, 25]]) == [[0, 30]]

    def test_garbage_dropped(self):
        merged = merge_intervals(
            [[10, 5], [-3, 4], ["x", "y"], [1], None, [0, 0]],  # type: ignore[list-item]
            [[1, 2]],
        )
        assert merged == [[1, 2]]

    def test_string_numbers_coerced(self):
        assert merge_intervals([["0", "5"]], [["5", "9"]]) == [[0.0, 9.0]]  # type: ignore[list-item]

    def test_two_devices_interleaved(self):
        # Устройство А смотрело начало, Б — конец: суммарное покрытие честное.
        a = [[0, 30], [30, 60]]
        b = [[55, 90]]
        assert merge_intervals(a, b) == [[0, 90]]


class TestCoverage:
    def test_full(self):
        assert coverage([[0, 100]], 100) == 1.0

    def test_partial(self):
        assert coverage([[0, 45]], 100) == 0.45

    def test_zero_duration(self):
        assert coverage([[0, 10]], 0) == 0.0

    def test_capped_at_one(self):
        # Интервалы длиннее duration (репорт с погрешностью) не дают >1.
        assert coverage([[0, 150]], 100) == 1.0


class TestIsWatched:
    def test_above_threshold(self):
        assert is_watched([[0, 91]], 100)

    def test_at_threshold(self):
        assert is_watched([[0, 90]], 100)

    def test_below_threshold(self):
        assert not is_watched([[0, 89]], 100)

    def test_skipped_middle(self):
        # Посмотрел начало и конец, промотав середину — не досмотрено.
        assert not is_watched([[0, 40], [60, 100]], 100)

    def test_no_intervals(self):
        assert not is_watched([], 100)


class TestTruncation:
    """Переполнение жертвует короткими кусками, а не концовкой ролика."""

    def _many(self, count: int, *, start: float = 0.0, step: float = 10.0) -> list[list[float]]:
        # Щели по 5с — merge их не смыкает (порог 0.5с).
        return [[start + i * step, start + i * step + 5.0] for i in range(count)]

    def test_capped_at_max(self):
        merged = merge_intervals(self._many(MAX_INTERVALS + 100), [])
        assert len(merged) == MAX_INTERVALS

    def test_tail_survives(self):
        # Главный регресс: раньше срез [:MAX] выбрасывал конец ролика — ровно
        # те проценты, которых требует гейт.
        source = self._many(MAX_INTERVALS + 100)
        merged = merge_intervals(source, [])
        assert merged[-1] == source[-1]

    def test_shortest_dropped_first(self):
        long_ones = [[i * 100.0, i * 100.0 + 50.0] for i in range(MAX_INTERVALS)]
        crumbs = [[i * 100.0 + 60.0, i * 100.0 + 60.3] for i in range(20)]
        merged = merge_intervals(long_ones, crumbs)
        assert len(merged) == MAX_INTERVALS
        assert all(end - start > 1 for start, end in merged)

    def test_two_full_devices_keep_the_end(self):
        # Два устройства по MAX_INTERVALS кусков: половину придётся выбросить,
        # но концовка ролика — та часть, ради которой существует гейт, —
        # обязана уцелеть (раньше срез [:MAX] выбрасывал именно её).
        a = self._many(MAX_INTERVALS)
        b = self._many(MAX_INTERVALS, start=MAX_INTERVALS * 10.0)
        merged = merge_intervals(a, b)
        assert len(merged) == MAX_INTERVALS
        assert merged[-1] == b[-1]

    def test_idempotent(self):
        once = merge_intervals(self._many(MAX_INTERVALS + 100), [])
        assert merge_intervals(once, []) == once

    def test_infinite_bounds_dropped(self):
        merged = merge_intervals([[0, math.inf], [math.nan, 5]], [[1, 2]])
        assert merged == [[1, 2]]


class TestNormalizeDuration:
    def test_finite(self):
        assert normalize_duration(53.243) == 53.243

    def test_none_and_garbage(self):
        assert normalize_duration(None) is None
        assert normalize_duration("нет") is None

    def test_non_finite(self):
        # JSON.stringify(Infinity) даёт null, но старые бандлы шлют и inf.
        assert normalize_duration(math.inf) is None
        assert normalize_duration(math.nan) is None

    def test_non_positive(self):
        assert normalize_duration(0) is None
        assert normalize_duration(-5) is None

    def test_absurd(self):
        assert normalize_duration(25 * 3600) is None


class TestResolveDuration:
    def setup_method(self):
        vp._warned.clear()

    def test_server_wins(self):
        assert resolve_duration(server=53.24, stored=999.0, incoming=1.0) == 53.24

    def test_first_client_value_accepted(self):
        assert resolve_duration(server=None, stored=None, incoming=100.0) == 100.0

    def test_stored_is_the_anchor(self):
        # Шум ±2% не двигает знаменатель: приняв «почти то же самое» на каждом
        # пинге, клиент за десяток пингов уполз бы за 1/0.9 и запер себя.
        assert resolve_duration(server=None, stored=100.0, incoming=100.02) == 100.0
        assert not vp._warned

    def test_out_of_corridor_ignored_and_warned(self):
        assert resolve_duration(
            server=None, stored=100.0, incoming=180.0, profile_id="p", media_id="m"
        ) == 100.0
        assert ("p", "m") in vp._warned

    def test_warning_deduped(self):
        for _ in range(5):
            resolve_duration(
                server=None, stored=100.0, incoming=180.0, profile_id="p", media_id="m"
            )
        assert len(vp._warned) == 1

    def test_unknown_everything(self):
        assert resolve_duration(server=None, stored=None, incoming=None) is None

    def test_broken_incoming_keeps_stored(self):
        assert resolve_duration(server=None, stored=100.0, incoming=math.inf) == 100.0

    def test_never_crosses_gate_corridor(self):
        # Регресс от КОНСТАНТЫ порога: как бы клиент ни двигал число, принятый
        # знаменатель не может вырасти настолько, чтобы 90% стали недостижимы.
        first = 100.0
        current = first
        for attempt in (100.5, 101.9, 103.0, 150.0, 99.0, 100.0):
            current = resolve_duration(server=None, stored=current, incoming=attempt)
            assert current / first <= 1 / WATCH_THRESHOLD

    def test_tolerance_is_narrow(self):
        # Коридор обязан быть уже, чем «завышение, ломающее гейт».
        assert 1 + DURATION_TOLERANCE < 1 / WATCH_THRESHOLD


class TestVideoProgressBody:
    """Приёмный лимит и «клиент не смог измерить» — часть контракта ручки."""

    def _payload(self, count: int, **over) -> dict:
        return {
            "media_id": "11111111-1111-1111-1111-111111111111",
            "intervals": [[float(i), float(i) + 0.5] for i in range(count)],
            "duration": 100.0,
            **over,
        }

    def test_accepts_at_least_what_we_store(self):
        # Инвариант: приёмный лимит НЕ МЕНЬШЕ хранимого. Обратное (200 против
        # 500) означало вечный 422 у того, кто уже накопил длинный список.
        body = VideoProgressBody(**self._payload(MAX_INTERVALS * 2))
        assert len(body.intervals) == MAX_INTERVALS * 2

    def test_rejects_beyond_limit(self):
        with pytest.raises(ValidationError):
            VideoProgressBody(**self._payload(MAX_INTERVALS * 2 + 1))

    def test_null_duration_accepted(self):
        # JSON.stringify(Infinity) === "null": 422 в ответ стоил бы человеку
        # всех интервалов пинга (баг «422 навсегда», ОС 24.08).
        body = VideoProgressBody(**self._payload(1, duration=None))
        assert body.duration is None
        assert resolve_duration(incoming=body.duration) is None

    def test_missing_duration_accepted(self):
        payload = self._payload(1)
        payload.pop("duration")
        assert VideoProgressBody(**payload).duration is None

    def test_infinite_duration_survives_to_resolver(self):
        body = VideoProgressBody(**self._payload(1, duration=math.inf))
        assert resolve_duration(stored=100.0, incoming=body.duration) == 100.0
