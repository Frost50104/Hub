"""План монтажа: отрезки гуся минус вставки, куски Hedra, кусочная склейка без
дыр, аргументы кусочного рендера, цена."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_piece_args_concat_and_mux():
    pieces = cp.timeline_pieces(
        20,
        [(5.0, 10.0)],
        [{"at": 15.0, "duration": 5.0}],
        first_chunk_input=1,
        first_insert_input=2,
    )
    sources = [Path("/c.mp4"), Path("/g0.mp4"), Path("/i0.mp4")]
    base = cp.piece_args(pieces[0], sources, Path("/p0.mp4"), width=1280, height=720, fps=30)
    assert base[:6] == ["-ss", "0.000", "-i", "/c.mp4", "-t", "5.000"]
    assert "-an" in base and base[base.index("-vf") + 1] == "fps=30,format=yuv420p"
    assert base[-1] == "/p0.mp4" and "libx264" in base
    goose = cp.piece_args(
        pieces[1], sources, Path("/p1.mp4"), width=1280, height=720, fps=30, threads=2
    )
    assert goose[:6] == ["-ss", "0.000", "-i", "/g0.mp4", "-t", "5.000"]
    vf = goose[goose.index("-vf") + 1]
    assert vf.startswith("scale=1280:720:force_original_aspect_ratio=decrease")
    assert "tpad=stop_mode=clone:stop_duration=7.000" in vf
    assert goose[goose.index("-threads") + 1] == "2"
    insert = cp.piece_args(pieces[3], sources, Path("/p3.mp4"), width=1280, height=720, fps=30)
    assert insert[3] == "/i0.mp4"
    # Одни и те же параметры кодека у всех кусков — иначе concat -c copy не склеит.
    assert (
        base[base.index("-c:v") : base.index("-c:v") + 8]
        == goose[goose.index("-c:v") : goose.index("-c:v") + 8]
    )
    lst = cp.concat_list([Path("/p0.mp4"), Path("/p1.mp4")])
    assert lst.splitlines() == ["file '/p0.mp4'", "file '/p1.mp4'"]
    concat = cp.concat_video_args(Path("/l.txt"), Path("/v.mp4"))
    assert concat[:4] == ["-f", "concat", "-safe", "0"] and concat[-3:] == ["-c", "copy", "/v.mp4"]
    mux = cp.mux_args(Path("/v.mp4"), Path("/c.mp4"), Path("/o.mp4"))
    assert mux[mux.index("-map") + 1] == "0:v:0" and "1:a:0" in mux
    assert mux[mux.index("-c:a") + 1] == "copy" and "+faststart" in mux and mux[-1] == "/o.mp4"
    voice = cp.voice_slice_args(Path("/c.mp4"), Path("/v.mp3"), 15.0, 30.0)
    assert (
        voice[:4] == ["-ss", "15.000", "-i", "/c.mp4"] and voice[voice.index("-t") + 1] == "15.000"
    )
    assert "-af" not in voice


def test_mute_intervals_and_voice_filter():
    # Слова чистовика: 14–16, 16.3–20, 24–29; кусок гуся 15–30.
    speech = [(14.0, 16.0), (16.3, 20.0), (24.0, 29.0)]
    mute = cp.mute_intervals(speech, 15.0, 30.0)
    # Зазор 16–16,3 короче min_gap — не глушим; 20,15–23,85 и 29,15–30 — глушим.
    assert mute == [(pytest.approx(5.15), pytest.approx(8.85)), (pytest.approx(14.15), 15.0)]
    assert (
        cp.mute_filter(mute) == "volume=0:enable='between(t,5.150,8.850)+between(t,14.150,15.000)'"
    )
    voice = cp.voice_slice_args(Path("/c.mp4"), Path("/v.mp3"), 15.0, 30.0, mute=mute)
    assert voice[voice.index("-af") + 1].startswith("volume=0:enable=")
    assert voice.index("-vn") < voice.index("-af") < voice.index("-ac")
    # Без транскрипта глушить нечего — и ничего не глушим.
    assert cp.mute_intervals([], 15.0, 30.0) == []
    # Речь целиком покрывает кусок — тоже пусто.
    assert cp.mute_intervals([(0.0, 100.0)], 15.0, 30.0) == []
