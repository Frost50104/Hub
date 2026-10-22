"""Нарезка звука на куски для STT и Hedra; срезы WAV через stdlib."""

from __future__ import annotations

import io
import struct
import wave

import pytest

from app.services.media import chunking


def test_plan_chunks_short_or_empty():
    assert chunking.plan_chunks(30, []) == [(0.0, 30.0)]
    assert chunking.plan_chunks(0, []) == []


def test_plan_chunks_cuts_at_nearest_silence():
    chunks = chunking.plan_chunks(
        120, [(48, 49), (52, 53), (95, 96)], target=50, max_len=55, min_len=20
    )
    assert chunks == [(0.0, 48.5), (48.5, 95.5), (95.5, 120.0)]
    assert all(e - s <= 55 + 1e-6 for s, e in chunks)


def test_plan_chunks_hard_cut_keeps_tail_not_shorter_than_min():
    assert chunking.plan_chunks(70, [], max_len=55, min_len=20) == [(0.0, 50.0), (50.0, 70.0)]
    chunks = chunking.plan_chunks(200, [], max_len=55, min_len=20)
    assert chunks == [(0.0, 55.0), (55.0, 110.0), (110.0, 165.0), (165.0, 200.0)]
    assert sum(e - s for s, e in chunks) == pytest.approx(200)
    assert all(e - s >= 20 for s, e in chunks)


def test_plan_chunks_ignores_silence_outside_window():
    # Тишина на 10-й секунде раньше min_len — не кандидат.
    chunks = chunking.plan_chunks(100, [(9, 11)], max_len=55, min_len=20)
    assert chunks == [(0.0, 55.0), (55.0, 100.0)]


def test_plan_hedra_chunks_splits_long_segments_by_gap():
    gaps = [(290, 291.0), (450, 452)]
    chunks = chunking.plan_hedra_chunks([(0, 700)], gaps, max_len=600)
    assert chunks == [(0.0, 451.0), (451.0, 700.0)]


def test_plan_hedra_chunks_hard_cut_and_merge_tiny_tail():
    assert chunking.plan_hedra_chunks([(0, 600.2)], [], max_len=600, min_len=0.5) == [(0.0, 600.2)]
    assert chunking.plan_hedra_chunks([(0, 1300)], [], max_len=600) == [
        (0.0, 600.0),
        (600.0, 1200.0),
        (1200.0, 1300.0),
    ]
    # Короткие отрезки короче min_len без предыдущего куска остаются.
    assert chunking.plan_hedra_chunks([(0, 0.2)], [], max_len=600) == [(0.0, 0.2)]


def test_read_wav_slices(tmp_path):
    path = tmp_path / "a.wav"
    rate = 16000
    samples = [1000] * rate + [2000] * rate + [3000] * rate
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    parts = list(chunking.read_wav_slices(path, [(0, 1), (1, 2.5), (2.5, 3), (2.9, 9)]))
    assert len(parts) == 4
    expected = [rate, int(rate * 1.5), rate // 2, int(rate * 0.1)]
    for blob, expect in zip(parts, expected, strict=True):
        with wave.open(io.BytesIO(blob), "rb") as r:
            assert r.getnframes() == expect
            assert r.getframerate() == rate
            assert r.getnchannels() == 1
    with wave.open(io.BytesIO(parts[1]), "rb") as r:
        assert struct.unpack("<h", r.readframes(1))[0] == 2000
