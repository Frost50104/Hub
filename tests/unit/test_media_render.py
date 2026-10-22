"""Команды чистовика: скрипт фильтров, два прохода loudnorm, анализ звука."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.media import render

MEASURED = {
    "input_i": -35.2,
    "input_tp": -0.1,
    "input_lra": 14.3,
    "input_thresh": -45.8,
    "target_offset": 0.3,
}


def test_filter_script_and_render_args():
    kept = [(0, 1), (2, 4)]
    script = render.filter_script(
        kept,
        denoise="afftdn=nf=-25:tn=1",
        i=-16,
        tp=-1.5,
        lra=11,
        measured=MEASURED,
        fps=30,
        scale_cap=1080,
    )
    v, a = script.strip().split(";\n")
    assert v == (
        "[0:v]select='between(t,0.000,1.000)+between(t,2.000,4.000)',setpts=N/FRAME_RATE/TB,"
        "fps=30,scale=-2:'min(ih,1080)':flags=bicubic,format=yuv420p[v]"
    )
    assert a == (
        "[0:a]aselect='between(t,0.000,1.000)+between(t,2.000,4.000)',asetpts=N/SR/TB,"
        "afftdn=nf=-25:tn=1,loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-35.2:measured_TP=-0.1:"
        "measured_LRA=14.3:measured_thresh=-45.8:offset=0.3:linear=true:print_format=summary[a]"
    )
    args = render.render_args(Path("/s.mp4"), Path("/d.mp4"), Path("/f.txt"), threads=1)
    assert args[:4] == ["-i", "/s.mp4", "-filter_complex_script", "/f.txt"]
    assert args[args.index("-map") + 1] == "[v]"
    assert "[a]" in args and "+faststart" in args and args[-1] == "/d.mp4"


def test_filter_script_without_denoise_and_offset():
    script = render.filter_script(
        [(0, 5)],
        denoise="",
        i=-16,
        tp=-1.5,
        lra=11,
        measured={k: v for k, v in MEASURED.items() if k != "target_offset"},
        fps=25,
        scale_cap=720,
    )
    assert "asetpts=N/SR/TB,loudnorm=" in script
    assert ":offset=0:" in script
    assert "fps=25,scale=-2:'min(ih,720)'" in script


def test_denoise_filter():
    assert render.denoise_filter("afftdn") == "afftdn=nf=-25:tn=1"
    assert render.denoise_filter("none") == ""
    with pytest.raises(ValueError, match="rnnoise"):
        render.denoise_filter("arnndn")
    assert render.denoise_filter("arnndn", rnnoise_model=Path("/m.rnnn")) == "arnndn=m=/m.rnnn"
    with pytest.raises(ValueError, match="шумодав"):
        render.denoise_filter("magic")


def test_pass1_and_analysis_args():
    args = render.loudnorm_pass1_args(Path("/s.mp4"), [(0, 5)], denoise="", i=-16, tp=-1.5, lra=11)
    assert args[args.index("-af") + 1] == (
        "aselect='between(t,0.000,5.000)',asetpts=N/SR/TB,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"
    )
    assert args[-3:] == ["-f", "null", "-"]
    assert "-vn" in args
    sd = render.silencedetect_args(Path("/a.wav"), threshold_db=-43.3, min_pause=1.5)
    assert sd[sd.index("-af") + 1] == "silencedetect=n=-43.3dB:d=1.5"
    assert "astats=measure_overall=Noise_floor" in render.noise_floor_args(Path("/a.wav"))[3]
    a16 = render.audio16k_args(Path("/s.mp4"), Path("/a.wav"))
    assert a16[a16.index("-ar") + 1] == "16000"
    assert a16[a16.index("-ac") + 1] == "1"
    assert "-vn" in a16 and a16[-1] == "/a.wav"
    voice = render.voice_track_args(Path("/s.mp4"), Path("/v.mp3"))
    assert "libmp3lame" in voice and voice[-1] == "/v.mp3"
