"""План монтажа: отрезки гуся минус вставки, куски Hedra, кусочная склейка без
дыр, скрипт фильтров, цена."""

from __future__ import annotations

from pathlib import Path

from app.services.media import compose_plan as cp

SEGMENTS = [
    {"s": 0, "e": 30, "kind": "speaker", "mode": "goose"},
    {"s": 30, "e": 60, "kind": "screen"},
    {"s": 60, "e": 100, "kind": "speaker", "mode": "keep"},
    {"s": 100, "e": 120, "kind": "speaker", "mode": "goose"},
]
INSERTS = [
    {"media_id": "i1", "at": 10, "duration": 5},
    {"media_id": "i2", "at": 115, "duration": 30},
]


def test_plan_goose_minus_inserts_and_cost():
    plan = cp.plan_compose(
        duration=120, segments=SEGMENTS, inserts=INSERTS, goose_enabled=True, resolution="720p"
    )
    assert plan.goose == [(0.0, 10.0), (15.0, 30.0), (100.0, 115.0)]
    assert plan.chunks == [(0.0, 10.0), (15.0, 30.0), (100.0, 115.0)]
    assert plan.goose_seconds == 40.0 and plan.billed_seconds == 40
    assert plan.cost_cents == 200  # 5 ¢/с в 720p
    assert plan.inserts[1]["duration"] == 5.0  # обрезана по концу
    assert plan.summary()["inserts"] == 2 and plan.summary()["chunks"] == 3


def test_plan_without_goose_is_free():
    plan = cp.plan_compose(
        duration=120, segments=SEGMENTS, inserts=INSERTS, goose_enabled=False, resolution="1080p"
    )
    assert plan.goose == [] and plan.chunks == [] and plan.cost_cents == 0
    assert plan.summary()["goose_seconds"] == 0


def test_timeline_pieces_cover_duration_without_gaps():
    pieces = cp.timeline_pieces(
        120,
        [(0.0, 10.0), (15.0, 30.0), (100.0, 115.0)],
        [{"at": 10.0, "duration": 5.0}, {"at": 115.0, "duration": 5.0}],
        first_chunk_input=1,
        first_insert_input=4,
    )
    assert [(p.kind, p.start, p.end, p.input_index) for p in pieces] == [
        ("goose", 0.0, 10.0, 1),
        ("insert", 10.0, 15.0, 4),
        ("goose", 15.0, 30.0, 2),
        ("base", 30.0, 100.0, 0),
        ("goose", 100.0, 115.0, 3),
        ("insert", 115.0, 120.0, 5),
    ]
    assert sum(p.length for p in pieces) == 120.0
    plain = cp.timeline_pieces(50, [], [], first_chunk_input=1, first_insert_input=1)
    assert [(p.kind, p.start, p.end) for p in plain] == [("base", 0.0, 50.0)]


def test_filter_script_and_render_args():
    pieces = cp.timeline_pieces(
        20,
        [(5.0, 10.0)],
        [{"at": 15.0, "duration": 5.0}],
        first_chunk_input=1,
        first_insert_input=2,
    )
    script = cp.filter_script(pieces, width=1280, height=720, fps=30)
    lines = script.strip().split(";\n")
    assert lines[0] == "[0:v]trim=start=0.000:end=5.000,setpts=PTS-STARTPTS[v0]"
    assert lines[1].startswith("[1:v]scale=1280:720:force_original_aspect_ratio=decrease")
    assert "tpad=stop_mode=clone:stop_duration=7.000,trim=start=0.000:end=5.000" in lines[1]
    assert lines[2] == "[0:v]trim=start=10.000:end=15.000,setpts=PTS-STARTPTS[v2]"
    assert lines[3].startswith("[2:v]scale=1280:720")
    assert lines[-1] == "[v0][v1][v2][v3]concat=n=4:v=1:a=0[vout]"
    args = cp.render_args(
        Path("/c.mp4"),
        [Path("/g0.mp4")],
        [Path("/i0.mp4")],
        Path("/f.txt"),
        Path("/o.mp4"),
        threads=2,
    )
    assert args[:6] == ["-i", "/c.mp4", "-i", "/g0.mp4", "-i", "/i0.mp4"]
    assert args[args.index("-map") + 1] == "[vout]" and "0:a:0" in args and args[-1] == "/o.mp4"
    voice = cp.voice_slice_args(Path("/c.mp4"), Path("/v.mp3"), 15.0, 30.0)
    assert (
        voice[:4] == ["-ss", "15.000", "-i", "/c.mp4"] and voice[voice.index("-t") + 1] == "15.000"
    )
