"""Паспорт ffprobe и план нормализации на сохранённых образцах JSON."""

from __future__ import annotations

from pathlib import Path

from app.services.media import normalize
from app.services.media.probe import parse_ffprobe

MP4 = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "231.5", "size": "35000000"},
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1280,
            "height": 720,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "60/1",
            "r_frame_rate": "60/1",
        },
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
    ],
}
MOV_HEVC = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.0"},
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "30000/1001",
            "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}],
        },
        {"codec_type": "audio", "codec_name": "aac"},
    ],
}
WEBM = {
    "format": {"format_name": "matroska,webm", "duration": "10.0"},
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "vp9",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "30/1",
        },
        {"codec_type": "audio", "codec_name": "opus"},
    ],
}
NOAUDIO = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "5"},
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1280,
            "height": 720,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "25/1",
        }
    ],
}
MP4_30 = {
    **MP4,
    "streams": [{**MP4["streams"][0], "avg_frame_rate": "30/1"}, MP4["streams"][1]],
}


def test_parse_ffprobe_mp4():
    p = parse_ffprobe(MP4)
    assert p.duration == 231.5
    assert p.fps == 60.0
    assert p.container == "mp4"
    assert p.has_audio and p.has_video
    assert p.size_bytes == 35000000
    assert p.display_size == (1280, 720)
    assert p.rotation == 0
    assert (p.sample_rate, p.channels) == (48000, 2)


def test_parse_ffprobe_rotation_and_fractional_fps():
    p = parse_ffprobe(MOV_HEVC)
    assert p.rotation == 270
    assert p.display_size == (1080, 1920)
    assert p.fps == 29.97
    assert p.vcodec == "hevc"


def test_parse_ffprobe_webm_and_tags_rotate():
    p = parse_ffprobe(WEBM)
    assert p.container == "webm"
    assert p.acodec == "opus"
    assert p.sample_rate is None and p.channels is None
    tagged = {**NOAUDIO, "streams": [{**NOAUDIO["streams"][0], "tags": {"rotate": "90"}}]}
    assert parse_ffprobe(tagged).rotation == 90


def test_parse_ffprobe_empty_and_bad_values():
    p = parse_ffprobe({})
    assert p.duration == 0.0
    assert not p.has_video and not p.has_audio
    assert p.container == "unknown"
    assert p.display_size is None
    bad = {
        "format": {"duration": "n/a", "size": "x"},
        "streams": [{"codec_type": "video", "avg_frame_rate": "0/0"}],
    }
    p = parse_ffprobe(bad)
    assert p.duration == 0.0 and p.size_bytes is None and p.fps is None


def test_plan_copy_vs_transcode():
    assert normalize.plan(parse_ffprobe(MP4)) == "transcode"  # 60 fps выше потолка
    assert normalize.plan(parse_ffprobe(MP4_30)) == "copy"
    assert normalize.plan(parse_ffprobe(NOAUDIO)) == "copy"
    assert normalize.plan(parse_ffprobe(MOV_HEVC)) == "transcode"
    assert normalize.plan(parse_ffprobe(WEBM)) == "transcode"
    big = {**MP4_30, "streams": [{**MP4_30["streams"][0], "height": 1440}, MP4_30["streams"][1]]}
    assert normalize.plan(parse_ffprobe(big)) == "transcode"
    rotated = {
        **MP4_30,
        "streams": [{**MP4_30["streams"][0], "tags": {"rotate": "90"}}, MP4_30["streams"][1]],
    }
    assert normalize.plan(parse_ffprobe(rotated)) == "transcode"
    mp3_audio = {"codec_type": "audio", "codec_name": "mp3"}
    mp3 = {**MP4_30, "streams": [MP4_30["streams"][0], mp3_audio]}
    assert normalize.plan(parse_ffprobe(mp3)) == "transcode"


def test_args_copy_and_transcode():
    src, dst = Path("/in.mov"), Path("/out.mp4")
    copy = normalize.args("copy", src, dst, parse_ffprobe(MP4_30))
    assert copy[:2] == ["-i", "/in.mov"]
    assert copy[copy.index("-c") + 1] == "copy"
    assert copy[-3:] == ["-movflags", "+faststart", "/out.mp4"]
    tr = normalize.args("transcode", src, dst, parse_ffprobe(MP4), threads=2)
    assert tr[tr.index("-vf") + 1] == "scale=-2:'min(ih,1080)':flags=bicubic,fps=30,format=yuv420p"
    assert "libx264" in tr and "aac" in tr
    assert tr[tr.index("-threads") + 1] == "2"
    assert tr[-3:] == ["-movflags", "+faststart", "/out.mp4"]
    tr2 = normalize.args("transcode", src, dst, parse_ffprobe(NOAUDIO))
    assert "aac" not in tr2
    assert "fps=25" in tr2[tr2.index("-vf") + 1]
