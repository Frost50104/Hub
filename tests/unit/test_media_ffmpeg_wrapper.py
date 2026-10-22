"""Обёртка ffmpeg: парсер `-progress`, потолок времени, и — при наличии
бинаря — живые прогоны: паспорт, тишина, рендер чистовика, таймаут, отмена."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.services.learn_media import mp4_has_faststart
from app.services.media import edl, ffmpeg, normalize, render, silence
from app.services.media.probe import parse_ffprobe

SLOW_SRC = ["-re", "-f", "lavfi", "-i", "testsrc=duration=30:size=64x64:rate=5", "-f", "null", "-"]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe не установлены"
)


def test_parse_progress_line():
    assert ffmpeg.parse_progress_line("out_time_us=1500000") == ("out_time_us", "1500000")
    assert ffmpeg.parse_progress_line(" speed= 2x ") == ("speed", "2x")
    assert ffmpeg.parse_progress_line("garbage") is None
    assert ffmpeg.parse_progress_line("") is None


def test_progress_feed_and_pct():
    p = ffmpeg.Progress()
    assert p.feed("frame=12") is False
    assert p.frames == 12
    assert p.feed("out_time_ms=2500000") is False  # микросекунды, несмотря на имя
    assert p.out_time_sec == 2.5
    p.feed("out_time_us=3000000")
    assert p.out_time_sec == 3.0
    p.feed("out_time_ms=1")  # после out_time_us игнорируется
    assert p.out_time_sec == 3.0
    p.feed("speed=2.5x")
    assert p.speed == 2.5
    p.feed("speed=N/A")
    assert p.speed is None
    assert p.feed("progress=continue") is True
    assert p.done is False
    assert p.feed("progress=end") is True
    assert p.done is True
    assert p.pct(6.0) == 50
    assert p.pct(None) is None
    assert p.pct(0) is None
    p.feed("out_time_us=-5")
    assert p.out_time_sec == 0.0
    p.feed("out_time_us=99000000")
    assert p.pct(6.0) == 100


def test_timeout_for():
    assert ffmpeg.timeout_for(None, factor=6) == 600
    assert ffmpeg.timeout_for(10, factor=6) == 600
    assert ffmpeg.timeout_for(1000, factor=6) == 6000


@pytest.fixture
def synthetic_mp4(tmp_path: Path) -> Path:
    """4 с: тест-таблица 320×240@30 и синус 440 Гц с цифровой тишиной на 1–3 с."""
    out = tmp_path / "src.mp4"
    subprocess.run(  # noqa: S603 — аргументы свои, без оболочки
        [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(between(t,1,3),0,0.5*sin(440*2*PI*t))':s=48000:d=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ],
        check=True,
    )
    return out


@needs_ffmpeg
async def test_probe_and_plan_on_real_file(synthetic_mp4: Path):
    p = parse_ffprobe(await ffmpeg.probe_json(synthetic_mp4, bin_path=FFPROBE))
    assert p.vcodec == "h264" and p.acodec == "aac" and p.container == "mp4"
    assert p.duration == pytest.approx(4.0, abs=0.2)
    assert (p.width, p.height, p.fps) == (320, 240, 30.0)
    assert normalize.plan(p) == "copy"


@needs_ffmpeg
async def test_silence_and_noise_floor_on_real_audio(synthetic_mp4: Path, tmp_path: Path):
    wav = tmp_path / "a.wav"
    await ffmpeg.run(render.audio16k_args(synthetic_mp4, wav), bin_path=FFMPEG, timeout_sec=60)
    assert wav.exists()
    nf_log = await ffmpeg.run(
        render.noise_floor_args(wav),
        bin_path=FFMPEG,
        timeout_sec=60,
        capture_stderr=True,
        loglevel="info",
    )
    thr = silence.threshold_db(silence.parse_noise_floor(nf_log))
    assert -60.0 <= thr <= -35.0
    log = await ffmpeg.run(
        render.silencedetect_args(wav, threshold_db=thr, min_pause=0.5),
        bin_path=FFMPEG,
        timeout_sec=60,
        capture_stderr=True,
        loglevel="info",
    )
    sil = silence.parse_silencedetect(log, duration=4.0)
    assert len(sil) == 1, log[-800:]
    s, e = sil[0]
    assert s == pytest.approx(1.0, abs=0.15)
    assert e == pytest.approx(3.0, abs=0.15)


@needs_ffmpeg
async def test_render_cleanup_chain_end_to_end(synthetic_mp4: Path, tmp_path: Path):
    removed = edl.compress_pauses([(1.0, 3.0)], keep=0.7, margin=0.2)  # вырезаем 1,3 с
    kept = edl.kept_intervals(removed, 4.0)
    log = await ffmpeg.run(
        render.loudnorm_pass1_args(synthetic_mp4, kept, denoise="", i=-16, tp=-1.5, lra=11),
        bin_path=FFMPEG,
        timeout_sec=60,
        capture_stderr=True,
        loglevel="info",
    )
    measured = silence.parse_loudnorm_json(log)
    script = tmp_path / "f.txt"
    script.write_text(
        render.filter_script(
            kept,
            denoise=render.denoise_filter("afftdn"),
            i=-16,
            tp=-1.5,
            lra=11,
            measured=measured,
            fps=30,
            scale_cap=1080,
        )
    )
    out = tmp_path / "out.mp4"
    seen: list[float] = []

    async def on_progress(p: ffmpeg.Progress) -> None:
        seen.append(p.out_time_sec)

    await ffmpeg.run(
        render.render_args(synthetic_mp4, out, script),
        bin_path=FFMPEG,
        timeout_sec=120,
        on_progress=on_progress,
    )
    p = parse_ffprobe(await ffmpeg.probe_json(out, bin_path=FFPROBE))
    assert p.duration == pytest.approx(4.0 - 1.3, abs=0.25)
    assert p.vcodec == "h264" and p.acodec == "aac" and p.pix_fmt == "yuv420p"
    assert mp4_has_faststart(out)
    assert seen and seen == sorted(seen)


@needs_ffmpeg
async def test_run_timeout_kills_process():
    t0 = time.monotonic()
    with pytest.raises(ffmpeg.FfmpegError, match="потолок"):
        await ffmpeg.run(
            SLOW_SRC,
            bin_path=FFMPEG,
            timeout_sec=1.0,
        )
    assert time.monotonic() - t0 < 10


@needs_ffmpeg
async def test_run_cancel_event_kills_process():
    cancel = asyncio.Event()

    async def trip() -> None:
        await asyncio.sleep(0.5)
        cancel.set()

    task = asyncio.create_task(trip())
    t0 = time.monotonic()
    with pytest.raises(ffmpeg.FfmpegError, match="отменено"):
        await ffmpeg.run(
            SLOW_SRC,
            bin_path=FFMPEG,
            timeout_sec=30,
            cancel=cancel,
        )
    assert time.monotonic() - t0 < 10
    await task


@needs_ffmpeg
async def test_run_failure_carries_stderr_tail(tmp_path: Path):
    with pytest.raises(ffmpeg.FfmpegError) as exc:
        await ffmpeg.run(
            ["-i", str(tmp_path / "missing.mp4"), "-f", "null", "-"],
            bin_path=FFMPEG,
            timeout_sec=10,
        )
    assert exc.value.code not in (None, 0)
    assert "missing.mp4" in exc.value.stderr_tail


@needs_ffmpeg
async def test_probe_json_failure(tmp_path: Path):
    with pytest.raises(ffmpeg.FfmpegError, match="ffprobe"):
        await ffmpeg.probe_json(tmp_path / "nope.mp4", bin_path=FFPROBE)
