"""Уровни звука по кадрам: разбор `ametadata`, порог от речи, доля громкого
времени, паузы по зазорам между словами, тихие отрезки без транскрипта."""

from __future__ import annotations

import pytest

from app.services.media import levels

AMETADATA = """frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-31.5
frame:1    pts:1600    pts_time:0.1
lavfi.astats.Overall.RMS_level=-inf
frame:2    pts:3200    pts_time:0.2
lavfi.astats.Overall.RMS_level=-45.25
frame:3    pts:4800    pts_time:0.3
lavfi.astats.Overall.RMS_level=nan
"""


def test_parse_levels_handles_inf_and_nan():
    frames = levels.parse_levels(AMETADATA)
    assert frames == [
        (0.0, -31.5),
        (0.1, levels.SILENT_DB),
        (0.2, -45.25),
        (0.3, levels.SILENT_DB),
    ]
    assert levels.parse_levels("") == []
    assert levels.frame_step(frames) == pytest.approx(0.1)
    assert levels.frame_step([]) == 0.1


def _frames(pattern: str, *, loud: float = -30.0, quiet: float = -60.0, step: float = 0.1):
    """`L` — громкий кадр, `.` — тихий, `x` — цифровая тишина."""
    out = []
    for i, ch in enumerate(pattern):
        v = loud if ch == "L" else quiet if ch == "." else levels.SILENT_DB
        out.append((round(i * step, 3), v))
    return out


def test_speech_level_threshold_and_fallback():
    frames = _frames("LLLL....LLLL")
    assert levels.speech_level_db(frames, [(0.0, 0.4), (0.8, 1.2)]) == -30.0
    assert levels.speech_level_db(frames, []) is None
    assert levels.threshold_db(-30.0) == -45.0
    assert levels.threshold_db(-30.0, offset=20) == -50.0
    # Рамки: слишком громкая речь → не ниже −30, слишком тихая → не выше −55.
    assert levels.threshold_db(-5.0) == -30.0
    assert levels.threshold_db(-80.0) == -55.0
    assert levels.threshold_db(None) == levels.DEFAULT_THRESHOLD_DB
    # Без транскрипта — верхняя четверть не-тихих кадров.
    mixed = _frames("LL......xx")
    assert levels.fallback_speech_level_db(mixed) == -30.0
    assert levels.fallback_speech_level_db(_frames("xxx")) is None


def test_loud_fraction_and_pauses_from_word_gaps():
    # Слова 0–0,4 и 2,0–2,4; зазор 0,4–2,0 с одним щелчком («пфр») на 1,0.
    frames = _frames("LLLL......L.........LLLL")
    thr = -45.0
    assert levels.loud_fraction(frames, (0.4, 2.0), thr) == pytest.approx(1 / 16)
    assert levels.loud_fraction(frames, (5.0, 6.0), thr) == 0.0
    gaps = [(0.4, 2.0), (2.4, 2.4)]
    assert levels.pauses_from_gaps(gaps, frames, thr, min_pause=1.5) == [(0.4, 2.0)]
    # Порог длины: зазор 1,6 с короче 2 с — не пауза.
    assert levels.pauses_from_gaps(gaps, frames, thr, min_pause=2.0) == []
    # Речь, пропущенная Whisper: зазор громок почти целиком — остаётся.
    speech_gap = _frames("LLLL..LLLLLLLLLLLL..LLLL")
    assert levels.pauses_from_gaps([(0.4, 2.0)], speech_gap, thr, min_pause=1.5) == []
    assert levels.pauses_from_gaps(
        [(0.4, 2.0)], speech_gap, thr, min_pause=1.5, max_loud_fraction=0.9
    ) == [(0.4, 2.0)]


def test_silent_runs_without_transcript():
    frames = _frames("LL.......LL....")
    # Тишина 0,2–0,9 (0,7 с) и хвост 1,1–1,5 (0,4 с до конца файла).
    assert levels.silent_runs(frames, -45.0, min_len=0.5) == [(0.2, 0.9)]
    assert levels.silent_runs(frames, -45.0, min_len=0.3) == [(0.2, 0.9), (1.1, 1.5)]
    assert levels.silent_runs([], -45.0, min_len=0.3) == []
