"""Разбор вывода ffmpeg-фильтров и порог тишины."""

from __future__ import annotations

import pytest

from app.services.media import silence

SILENCE_LOG = """
[silencedetect @ 0x1] silence_start: 1.52
[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 2.48
frame=  120 fps=0.0 q=-0.0 size=N/A
[silencedetect @ 0x1] silence_start: 10
"""

LOUDNORM = """[Parsed_loudnorm_1 @ 0x1]
{
\t"input_i" : "-35.21",
\t"input_tp" : "-0.10",
\t"input_lra" : "14.30",
\t"input_thresh" : "-45.80",
\t"output_i" : "-16.02",
\t"target_offset" : "0.30"
}
"""


def test_parse_silencedetect_closes_tail_with_duration():
    assert silence.parse_silencedetect(SILENCE_LOG) == [(1.52, 4.0)]
    assert silence.parse_silencedetect(SILENCE_LOG, duration=12.0) == [(1.52, 4.0), (10.0, 12.0)]
    # Длительность меньше начала хвоста — хвост отбрасывается.
    assert silence.parse_silencedetect(SILENCE_LOG, duration=9.0) == [(1.52, 4.0)]


def test_parse_silencedetect_negative_start_clamped():
    assert silence.parse_silencedetect("silence_start: -0.02\nsilence_end: 1.0") == [(0.0, 1.0)]
    assert silence.parse_silencedetect("silence_end: 1.0") == []


def test_noise_floor_and_threshold():
    log = (
        "[Parsed_astats_0 @ 0x1] Channel: 1\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -58.1\n"
        "[Parsed_astats_0 @ 0x1] Overall\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -55.3\n"
    )
    assert silence.parse_noise_floor(log) == -55.3
    assert silence.parse_noise_floor("nothing") is None
    assert silence.parse_noise_floor("Noise floor dB: -inf") is None
    assert silence.threshold_db(-55.3) == pytest.approx(-43.3)
    assert silence.threshold_db(-80) == -60.0
    assert silence.threshold_db(-10) == -35.0
    assert silence.threshold_db(None) == -40.0


def test_parse_loudnorm_json():
    assert silence.parse_loudnorm_json(LOUDNORM) == {
        "input_i": -35.21,
        "input_tp": -0.1,
        "input_lra": 14.3,
        "input_thresh": -45.8,
        "target_offset": 0.3,
    }
    with pytest.raises(ValueError, match="не найден"):
        silence.parse_loudnorm_json("no json here")
    with pytest.raises(ValueError, match="нет полей"):
        silence.parse_loudnorm_json('{"input_i": "-1"}')
