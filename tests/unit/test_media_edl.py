"""EDL чистовика: интервалы, паузы, ужатие, перемаппинг — чистая математика."""

from __future__ import annotations

import pytest

from app.services.media import edl


def approx_intervals(actual, expected):
    assert len(actual) == len(expected)
    for (a0, a1), (e0, e1) in zip(actual, expected, strict=True):
        assert a0 == pytest.approx(e0)
        assert a1 == pytest.approx(e1)


def test_normalize_merges_and_sorts():
    assert edl.normalize([(5, 6), (1, 2), (2, 3), (2.5, 2.8), (9, 9)]) == [(1.0, 3.0), (5.0, 6.0)]
    assert edl.normalize([]) == []


def test_intersect_and_subtract():
    assert edl.intersect([(0, 10)], [(2, 3), (8, 12)]) == [(2.0, 3.0), (8.0, 10.0)]
    assert edl.subtract([(0, 10)], [(2, 3), (8, 12)]) == [(0.0, 2.0), (3.0, 8.0)]
    assert edl.subtract([(0, 10)], []) == [(0.0, 10.0)]
    assert edl.subtract([(2, 3)], [(0, 10)]) == []
    assert edl.total([(0, 1), (0.5, 2)]) == 2.0


def test_pauses_intersect_transcript_gaps_and_threshold():
    silences = [(1.0, 4.0), (10.0, 10.8), (20.0, 23.0)]
    gaps = [(0.0, 3.0), (10.0, 11.0), (19.0, 30.0)]
    # (1,3) = 2 с — пауза; (10,10.8) короче порога; (20,23) — пауза.
    assert edl.pauses(silences, gaps, min_pause=1.5) == [(1.0, 3.0), (20.0, 23.0)]
    # Без транскрипта — только тишина.
    assert edl.pauses(silences, None, min_pause=1.5) == [(1.0, 4.0), (20.0, 23.0)]


def test_compress_pauses_keeps_edges():
    approx_intervals(edl.compress_pauses([(10.0, 13.0)], keep=0.7, margin=0.2), [(10.35, 12.65)])
    # Пауза длиной ровно keep — резать нечего.
    assert edl.compress_pauses([(10.0, 10.7)], keep=0.7, margin=0.2) == []
    # Поле больше половины keep — побеждает поле.
    approx_intervals(edl.compress_pauses([(0.0, 2.0)], keep=0.2, margin=0.5), [(0.5, 1.5)])


def test_kept_intervals_complement():
    kept = edl.kept_intervals([(1, 2), (5, 7)], 10)
    assert kept == [(0.0, 1.0), (2.0, 5.0), (7.0, 10.0)]
    assert edl.total(kept) == 7.0
    assert edl.kept_intervals([], 3) == [(0.0, 3.0)]


def test_remap_time_monotonic_and_shifts():
    removed = [(1.0, 2.0), (5.0, 7.0)]
    assert edl.remap_time(0.5, removed) == 0.5
    assert edl.remap_time(1.5, removed) == 1.0  # внутри вырезанного → его начало
    assert edl.remap_time(3.0, removed) == 2.0
    assert edl.remap_time(6.0, removed) == 4.0
    assert edl.remap_time(8.0, removed) == 5.0
    ts = [i / 10 for i in range(0, 101)]
    mapped = [edl.remap_time(t, removed) for t in ts]
    assert mapped == sorted(mapped)
    assert mapped[-1] == pytest.approx(10 - 3)


def test_remap_segments_drops_collapsed_and_maps_words():
    removed = [(1.0, 2.0)]
    segs = [
        {"s": 0.0, "e": 0.9, "t": "а", "w": [[0.0, 0.4, "а"]]},
        {"s": 1.2, "e": 1.8, "t": "в паузе"},
        {"s": 2.5, "e": 3.0, "t": "б", "w": [[2.5, 3.0, "б"]]},
    ]
    out = edl.remap_segments(segs, removed)
    assert [(x["s"], x["e"], x["t"]) for x in out] == [(0.0, 0.9, "а"), (1.5, 2.0, "б")]
    assert out[0]["w"] == [[0.0, 0.4, "а"]]
    assert out[1]["w"] == [[1.5, 2.0, "б"]]


def test_select_expr():
    assert edl.select_expr([(0, 1), (2.5, 4)]) == "between(t,0.000,1.000)+between(t,2.500,4.000)"
    assert edl.select_expr([]) == "0"
