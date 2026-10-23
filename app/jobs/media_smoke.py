"""Проверка конвейера видео после деплоя: ffmpeg/ffprobe на месте и нужной
версии, фильтры и кодеки собраны, синтетический рендер проходит через боевой
`filter_script`, расшифровка настроена, очередь без протухших аренд.

Зовёт `deploy/deploy.sh`, если юнит `-media` активен. Код возврата: 0 —
ffmpeg работает; 1 — нет (деплой печатает WARNING и не падает). Состояние
STT/Hedra печатается строками журнала и на код не влияет: за них отвечает
`GET /api/health/media`.

    cd /opt/signaris-hub && .venv/bin/python -m app.jobs.media_smoke
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from sqlalchemy import func, select

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.media import MediaJob
from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart
from app.services.media import edl, ffmpeg, gate, render
from app.services.media.probe import parse_ffprobe

log = structlog.get_logger("jobs.media_smoke")

REQUIRED_FILTERS = ("afftdn", "loudnorm", "silencedetect", "astats", "aselect", "select", "concat")
REQUIRED_ENCODERS = ("libx264", "aac")
MIN_MAJOR = 6


def _run(cmd: list[str]) -> str:
    return subprocess.run(  # noqa: S603 — аргументы свои, без оболочки
        cmd, capture_output=True, text=True, timeout=60, check=False
    ).stdout


def ffmpeg_version(bin_path: str) -> tuple[int, str]:
    first = _run([bin_path, "-version"]).splitlines()[:1]
    line = first[0] if first else ""
    m = re.search(r"version\s+(?:n)?(\d+)", line)
    return (int(m.group(1)) if m else 0), line[:80]


def missing_features(bin_path: str) -> list[str]:
    filters = _run([bin_path, "-hide_banner", "-filters"])
    encoders = _run([bin_path, "-hide_banner", "-encoders"])
    missing = [f"filter:{f}" for f in REQUIRED_FILTERS if not re.search(rf"\s{f}\s", filters)]
    missing += [f"encoder:{e}" for e in REQUIRED_ENCODERS if not re.search(rf"\s{e}\s", encoders)]
    return missing


async def synthetic_render(bin_ffmpeg: str, bin_ffprobe: str, workdir: Path) -> float:
    """2,5 с тест-таблицы с синусом → чистовик с вырезанной серединой → длительность."""
    src = workdir / "src.mp4"
    await ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2.5:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        bin_path=bin_ffmpeg,
        timeout_sec=120,
    )
    kept = edl.kept_intervals([(1.0, 1.5)], 2.5)
    log = await ffmpeg.run(
        render.loudnorm_pass1_args(src, kept, denoise="", i=-16, tp=-1.5, lra=11),
        bin_path=bin_ffmpeg,
        timeout_sec=120,
        capture_stderr=True,
        loglevel="info",
    )
    from app.services.media.silence import parse_loudnorm_json

    measured = parse_loudnorm_json(log)
    script = workdir / "filters.txt"
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
    out = workdir / "out.mp4"
    await ffmpeg.run(render.render_args(src, out, script), bin_path=bin_ffmpeg, timeout_sec=120)
    if not mp4_has_faststart(out):
        raise RuntimeError("рендер без faststart")
    probe = parse_ffprobe(await ffmpeg.probe_json(out, bin_path=bin_ffprobe))
    duration = mp4_duration_seconds(out) or probe.duration
    if not (1.6 <= duration <= 2.4):
        raise RuntimeError(f"длительность чистовика {duration:.2f} с вместо ≈2,0")
    return duration


async def expired_leases() -> int:
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(MediaJob)
                    .where(MediaJob.status == "running", MediaJob.lease_until < datetime.now(UTC))
                )
            ).scalar_one()
        )


def stt_status(timeout: float = 5.0) -> str:
    settings = get_settings()
    if settings.media_stt_provider == "openai":
        return "openai" if gate.stt_configured() else "openai_unconfigured"
    if not settings.media_stt_url:
        return "unconfigured"
    try:
        resp = httpx.get(f"{settings.media_stt_url.rstrip('/')}/health", timeout=timeout)
        return str(resp.json().get("status"))
    except (httpx.HTTPError, ValueError, AttributeError):
        return "unreachable"


async def run() -> int:
    settings = get_settings()
    if not gate.env_enabled():
        log.info("media.smoke_skipped", reason="SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED=false")
        return 0
    bin_ffmpeg = shutil.which(settings.media_ffmpeg_bin)
    bin_ffprobe = shutil.which(settings.media_ffprobe_bin)
    if not bin_ffmpeg or not bin_ffprobe:
        log.error("media.smoke_failed", reason="ffmpeg_missing")
        return 1
    major, banner = ffmpeg_version(bin_ffmpeg)
    if major < MIN_MAJOR:
        log.error("media.smoke_failed", reason="ffmpeg_too_old", version=banner)
        return 1
    missing = missing_features(bin_ffmpeg)
    if missing:
        log.error("media.smoke_failed", reason="ffmpeg_features", missing=missing)
        return 1
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="media-smoke-") as tmp:
        try:
            duration = await synthetic_render(bin_ffmpeg, bin_ffprobe, Path(tmp))
        except Exception as exc:  # noqa: BLE001 — любая ошибка = провал проверки
            log.error("media.smoke_failed", reason="render", err=str(exc)[:300])
            return 1
    leases = await expired_leases()
    try:
        import cv2  # noqa: PLC0415 — проверка наличия, не работа

        opencv = cv2.__version__
    except ImportError:
        opencv = None
    log.info(
        "media.smoke_ok",
        opencv=opencv,
        ffmpeg=banner,
        render_sec=round(time.monotonic() - started, 1),
        output_sec=round(duration, 2),
        stt=stt_status(),
        stt_url=settings.media_stt_url,
        avatar=gate.avatar_env_enabled(),
        expired_leases=leases,
    )
    return 0


def main() -> int:
    log_config.configure()
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
