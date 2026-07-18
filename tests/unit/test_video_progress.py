"""Юнит-тесты video_progress: merge интервалов + покрытие ≥90%."""

from __future__ import annotations

from app.services.video_progress import coverage, is_watched, merge_intervals


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
