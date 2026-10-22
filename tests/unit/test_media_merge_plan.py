"""План сборки из записей: целевой формат, режим части, аргументы, concat."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.media import merge
from app.services.media.probe import Probe


def probe(**kw) -> Probe:
    base = {
        "duration": 10.0,
        "width": 1280,
        "height": 720,
        "fps": 30.0,
        "vcodec": "h264",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "rotation": 0,
        "has_audio": True,
        "container": "mp4",
        "size_bytes": 1,
        "sample_rate": 48000,
        "channels": 2,
    }
    base.update(kw)
    return Probe(**base)


def test_plan_target_best_height_capped_and_16_9():
    target = merge.plan_target([probe(), probe(width=1920, height=1080, fps=60)])
    assert (target.width, target.height, target.fps) == (1920, 1080, 30.0)
    target = merge.plan_target([probe(width=640, height=480, fps=25), probe(height=360, width=640)])
    assert (target.width, target.height, target.fps) == (854, 480, 30.0)
    target = merge.plan_target([probe(width=2560, height=1440)], scale_cap=720)
    assert (target.width, target.height) == (1280, 720)
    # Повёрнутый телефонный MOV: высота кадра — после поворота.
    target = merge.plan_target([probe(width=1920, height=1080, rotation=90)])
    assert (target.width, target.height) == (1920, 1080)
    with pytest.raises(ValueError):
        merge.plan_target([probe(vcodec=None, width=None, height=None)])


def test_part_duration_and_mode():
    t = merge.Target(width=1280, height=720, fps=30.0)
    assert merge.part_duration(probe(), trim_start=2, trim_end=8) == 6
    assert merge.part_duration(probe(), trim_start=2, trim_end=50) == 8
    assert merge.part_mode(probe(), t) == "copy"
    assert merge.part_mode(probe(), t, trim_start=1) == "transcode"
    assert merge.part_mode(probe(), t, trim_end=5) == "transcode"
    assert merge.part_mode(probe(fps=25), t) == "transcode"
    assert merge.part_mode(probe(width=640, height=360), t) == "transcode"
    assert merge.part_mode(probe(sample_rate=44100), t) == "transcode"
    assert merge.part_mode(probe(has_audio=False, acodec=None), t) == "transcode"
    assert merge.part_mode(probe(container="webm", vcodec="vp9"), t) == "transcode"
    assert merge.part_mode(probe(rotation=90, width=720, height=1280), t) == "transcode"


def test_part_args_transcode_with_trim_pad_and_silence():
    t = merge.Target(width=1280, height=720, fps=30.0)
    src, dst = Path("/p.mp4"), Path("/o.mp4")
    args = merge.part_args(src, dst, probe(), t, mode="transcode", trim_start=2.5, trim_end=8)
    assert args[:4] == ["-ss", "2.500", "-i", "/p.mp4"]
    assert args[args.index("-t") + 1] == "5.500"
    assert args[args.index("-vf") + 1] == (
        "scale=1280:720:force_original_aspect_ratio=decrease:flags=bicubic,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
    )
    assert "libx264" in args and "aac" in args and args[-1] == "/o.mp4"
    assert "anullsrc" not in " ".join(args)
    silent = merge.part_args(src, dst, probe(has_audio=False, acodec=None), t, mode="transcode")
    joined = " ".join(silent)
    assert "-f lavfi -i anullsrc=r=48000:cl=stereo" in joined
    assert silent[silent.index("-t") + 1] == "10.000"
    assert "1:a:0" in silent
    plain = merge.part_args(src, dst, probe(), t, mode="transcode")
    assert "-ss" not in plain and "-t" not in plain
    copy = merge.part_args(src, dst, probe(), t, mode="copy")
    assert copy == ["-i", "/p.mp4", "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "/o.mp4"]


def test_concat_list_and_args():
    text = merge.concat_list([Path("/a/part-00.mp4"), Path("/a/it's.mp4")])
    assert text == "file '/a/part-00.mp4'\nfile '/a/it'\\''s.mp4'\n"
    args = merge.concat_args(Path("/a/list.txt"), Path("/a/out.mp4"))
    assert args[:6] == ["-f", "concat", "-safe", "0", "-i", "/a/list.txt"]
    assert args[-3:] == ["-movflags", "+faststart", "/a/out.mp4"]
