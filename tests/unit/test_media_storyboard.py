"""Раскадровка: маска спикера, сглаживание, отрезки, вставки, где рисует гусь."""

from __future__ import annotations

import pytest

from app.services.media import storyboard as sb


def test_speaker_mask_runs_and_smoothing():
    ratios = [0.3] * 10 + [0.0] * 10 + [0.3] * 10
    assert sb.runs(sb.speaker_mask(ratios, thr=0.12)) == [(0.0, 10.0), (20.0, 30.0)]
    noisy = [True] * 5 + [False] + [True] * 5
    assert sb.smooth_mask(noisy, window=5) == [True] * 11
    assert sb.smooth_mask([], window=5) == []
    assert sb.smooth_mask([True, False], window=1) == [True, False]
    assert sb.runs([]) == []


def test_merge_runs_bridges_and_drops_short():
    runs_ = [(0, 10), (11.5, 20), (30, 32)]
    assert sb.merge_runs(runs_, min_len=4, bridge_gap=2) == [(0.0, 20.0)]
    assert sb.merge_runs(runs_, min_len=1, bridge_gap=1) == [
        (0.0, 10.0),
        (11.5, 20.0),
        (30.0, 32.0),
    ]


def test_snap_to_cuts():
    assert sb.snap_to_cuts([(10, 20)], [9.2, 20.9, 50], tolerance=1.5) == [(9.2, 20.9)]
    assert sb.snap_to_cuts([(10, 20)], [5], tolerance=1.5) == [(10.0, 20.0)]
    # Ближайшая из двух подходящих.
    assert sb.snap_to_cuts([(10, 20)], [9.0, 10.4], tolerance=1.5) == [(10.4, 20.0)]


def test_build_segments_covers_duration():
    ratios = [0.0] * 30 + [0.4] * 60 + [0.0] * 30
    assert sb.build_segments(ratios, duration=120) == [
        {"s": 0.0, "e": 30.0, "kind": "screen"},
        {"s": 30.0, "e": 90.0, "kind": "speaker", "mode": "goose"},
        {"s": 90.0, "e": 120.0, "kind": "screen"},
    ]
    assert sb.build_segments([0.0] * 10, duration=10) == [{"s": 0.0, "e": 10.0, "kind": "screen"}]
    assert sb.build_segments([0.5] * 10, duration=10) == [
        {"s": 0.0, "e": 10.0, "kind": "speaker", "mode": "goose"}
    ]
    # Короткий всплеск лица короче min_len не становится отрезком.
    ratios = [0.0] * 20 + [0.5] * 2 + [0.0] * 20
    assert sb.build_segments(ratios, duration=42) == [{"s": 0.0, "e": 42.0, "kind": "screen"}]


def test_validate_segments():
    ok = sb.validate_segments(
        [{"s": 0, "e": 5, "kind": "screen"}, {"s": 5, "e": 10, "kind": "speaker"}], duration=10
    )
    assert ok[1]["mode"] == "goose"
    assert "mode" not in ok[0]
    with pytest.raises(ValueError, match="разрывом"):
        sb.validate_segments(
            [{"s": 0, "e": 4, "kind": "screen"}, {"s": 5, "e": 10, "kind": "speaker"}], duration=10
        )
    with pytest.raises(ValueError, match="до конца"):
        sb.validate_segments([{"s": 0, "e": 10, "kind": "screen"}], duration=12)
    with pytest.raises(ValueError, match="вид"):
        sb.validate_segments([{"s": 0, "e": 10, "kind": "cat"}], duration=10)
    with pytest.raises(ValueError, match="режим"):
        sb.validate_segments([{"s": 0, "e": 10, "kind": "speaker", "mode": "x"}], duration=10)
    with pytest.raises(ValueError, match="режима нет"):
        sb.validate_segments([{"s": 0, "e": 10, "kind": "screen", "mode": "goose"}], duration=10)
    with pytest.raises(ValueError, match="Пустой"):
        sb.validate_segments(
            [{"s": 0, "e": 0.01, "kind": "screen"}, {"s": 0.01, "e": 10, "kind": "screen"}],
            duration=10,
        )


def test_validate_inserts_and_goose_intervals():
    ins = sb.validate_inserts(
        [{"media_id": "b", "at": 50, "duration": 30}, {"media_id": "a", "at": 10, "duration": 5}],
        duration=60,
    )
    assert [i["media_id"] for i in ins] == ["a", "b"]
    assert ins[1]["duration"] == 10  # обрезана по концу чистовика
    with pytest.raises(ValueError, match="пересекаются"):
        sb.validate_inserts(
            [
                {"media_id": "a", "at": 10, "duration": 5},
                {"media_id": "b", "at": 12, "duration": 5},
            ],
            duration=60,
        )
    with pytest.raises(ValueError, match="вне видео"):
        sb.validate_inserts([{"media_id": "a", "at": 60, "duration": 5}], duration=60)
    with pytest.raises(ValueError, match="нулевой"):
        sb.validate_inserts([{"media_id": "a", "at": 6, "duration": 0}], duration=60)
    segs = [
        {"s": 0, "e": 30, "kind": "speaker", "mode": "goose"},
        {"s": 30, "e": 40, "kind": "screen"},
        {"s": 40, "e": 60, "kind": "speaker", "mode": "keep"},
    ]
    assert sb.goose_intervals(segs, ins) == [(0.0, 10.0), (15.0, 30.0)]
    assert sb.goose_intervals(segs) == [(0.0, 30.0)]
    assert sb.insert_intervals(ins) == [(10.0, 15.0), (50.0, 60.0)]
