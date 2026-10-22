"""Воркер конвейера на живой БД и живом ffmpeg: нормализация MOV на месте
(ремукс), MP4 60 fps без faststart (перекодирование), сборка из двух частей
с подрезкой и тишиной, отмена до старта, остановка воркера (задание обратно в
очередь без потери попытки), неизвестный вид, финальная ошибка.

Бинарь нужен настоящий (`skipif`): математика покрыта юнитами, здесь — что
аргументы, собранные чистыми функциями, ffmpeg принимает.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaJob, MediaPart
from app.services.learn_media import mp4_has_faststart
from app.services.media import ffmpeg as ffmpeg_mod
from app.services.media import jobs, storage
from app.services.media.probe import parse_ffprobe
from app.workers import media as worker

pytestmark = pytest.mark.integration

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="нет ffmpeg")


@pytest.fixture(autouse=True)
def _engine_per_test(_fresh_engine):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "attachments_root", tmp_path)
    monkeypatch.setattr(s, "media_min_free_bytes", 0)
    monkeypatch.setattr(s, "media_host_lock_path", tmp_path / "media.lock")
    monkeypatch.setattr(s, "media_job_lease_sec", 120)
    return s


def _gen(
    path: Path,
    *,
    fps: int = 30,
    size: str = "320x240",
    audio: bool = True,
    dur: float = 2.0,
    faststart: bool = True,
    fmt: str | None = None,
) -> None:
    cmd = [
        FFMPEG,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={dur}:size={size}:rate={fps}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=48000"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-ac", "2", "-shortest"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    if fmt:
        cmd += ["-f", fmt]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)  # noqa: S603


async def _media(
    tenant_id,
    env,
    name: str,
    *,
    status="ready",
    role="content",
    mime="video/mp4",
    duration=None,
    body: Path | None = None,
) -> MediaFile:
    async with tenant_scoped_session(tenant_id) as db:
        media = MediaFile(
            tenant_id=tenant_id,
            kind="video",
            role=role,
            status=status,
            storage_key="",
            file_name=name,
            mime=mime,
            size_bytes=1,
            duration_sec=duration,
        )
        db.add(media)
        await db.flush()
        media.storage_key = f"{tenant_id}/learn/media/{media.id}-{name}"
        await db.commit()
    dest = Path(env.attachments_root) / media.storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    if body is not None:
        shutil.copy(body, dest)
    return media


async def _enqueue(tenant_id, media_id, kind, **kw) -> uuid.UUID:
    async with tenant_scoped_session(tenant_id) as db:
        job = await jobs.enqueue(db, tenant_id=tenant_id, media_id=media_id, kind=kind, **kw)
        await db.commit()
        return job.id


async def _reload(tenant_id, media_id, job_id):
    async with tenant_scoped_session(tenant_id) as db:
        media = (await db.execute(select(MediaFile).where(MediaFile.id == media_id))).scalar_one()
        job = (await db.execute(select(MediaJob).where(MediaJob.id == job_id))).scalar_one()
        return media, job


async def _run(env, tenant_id, *, stop=None) -> str | None:
    return await worker.run_once(
        settings=env,
        stop=stop or asyncio.Event(),
        lock=storage.HostLock(env.media_host_lock_path),
        worker_id="test",
        heartbeat_sec=0.2,
        tenant_id=tenant_id,
    )


async def _probe(path: Path):
    return parse_ffprobe(await ffmpeg_mod.probe_json(path, bin_path=FFPROBE))


@needs_ffmpeg
async def test_normalize_mov_is_remuxed_in_place(env, tenant_id, tmp_path):
    src = tmp_path / "clip.mov"
    _gen(src, fmt="mov", faststart=False)
    media = await _media(
        tenant_id, env, "clip.mov", status="processing", mime="video/quicktime", body=src
    )
    job_id = await _enqueue(tenant_id, media.id, "normalize")
    old_path = Path(env.attachments_root) / media.storage_key

    assert await _run(env, tenant_id) == "done"

    media, job = await _reload(tenant_id, media.id, job_id)
    assert job.status == "done" and job.result["mode"] == "copy"
    assert job.result["elapsed_sec"] >= 0 and job.output_media_id == media.id
    assert media.status == "ready" and media.mime == "video/mp4"
    assert media.storage_key.endswith(f"{media.id}-clip.mp4")
    assert media.file_name == "clip.mp4"
    assert media.duration_sec == pytest.approx(2.0, abs=0.2)
    new_path = Path(env.attachments_root) / media.storage_key
    assert mp4_has_faststart(new_path) and media.size_bytes == new_path.stat().st_size
    assert not old_path.exists()
    tmp_root = Path(env.attachments_root) / str(tenant_id) / "learn" / "media" / ".tmp"
    assert not list(tmp_root.glob("*"))


@needs_ffmpeg
async def test_normalize_60fps_mp4_without_faststart_is_transcoded(env, tenant_id, tmp_path):
    src = tmp_path / "fast.mp4"
    _gen(src, fps=60, faststart=False)
    media = await _media(tenant_id, env, "fast.mp4", status="processing", body=src)
    job_id = await _enqueue(tenant_id, media.id, "normalize")

    assert await _run(env, tenant_id) == "done"

    media, job = await _reload(tenant_id, media.id, job_id)
    assert job.result["mode"] == "transcode"
    out = Path(env.attachments_root) / media.storage_key
    # Имя ключа совпало с исходным (`-fast.mp4`) — заменено на месте.
    assert out == tmp_path / f"{tenant_id}/learn/media/{media.id}-fast.mp4"
    probe = await _probe(out)
    assert probe.fps == 30.0 and mp4_has_faststart(out)
    assert media.status == "ready"


@needs_ffmpeg
async def test_merge_two_parts_with_trim_and_silence(env, tenant_id, tmp_path):
    a_src, b_src = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _gen(a_src, size="320x240", fps=30, dur=3.0)
    _gen(b_src, size="640x360", fps=25, dur=2.0, audio=False)
    a = await _media(tenant_id, env, "a.mp4", role="part", duration=3.0, body=a_src)
    b = await _media(tenant_id, env, "b.mp4", role="part", duration=2.0, body=b_src)
    merged = await _media(tenant_id, env, "merged.mp4", status="processing")
    async with tenant_scoped_session(tenant_id) as db:
        db.add(
            MediaPart(
                merged_media_id=merged.id,
                position=0,
                tenant_id=tenant_id,
                source_media_id=a.id,
                trim_start_sec=0.0,
            )
        )
        db.add(
            MediaPart(
                merged_media_id=merged.id,
                position=1,
                tenant_id=tenant_id,
                source_media_id=b.id,
                trim_start_sec=0.5,
                trim_end_sec=1.5,
            )
        )
        await db.commit()
    job_id = await _enqueue(tenant_id, merged.id, "merge")

    assert await _run(env, tenant_id) == "done"

    merged, job = await _reload(tenant_id, merged.id, job_id)
    assert job.status == "done"
    assert job.result["target"] == {"w": 640, "h": 360, "fps": 30.0}
    assert [p["mode"] for p in job.result["parts"]] == ["transcode", "transcode"]
    assert merged.status == "ready"
    out = Path(env.attachments_root) / merged.storage_key
    probe = await _probe(out)
    assert (probe.width, probe.height) == (640, 360)
    assert probe.has_audio and probe.acodec == "aac"
    assert merged.duration_sec == pytest.approx(4.0, abs=0.3)
    assert mp4_has_faststart(out)


@needs_ffmpeg
async def test_cancel_requested_before_start_marks_media_failed(env, tenant_id, tmp_path):
    src = tmp_path / "c.mov"
    _gen(src, fmt="mov")
    media = await _media(tenant_id, env, "c.mov", status="processing", body=src)
    job_id = await _enqueue(tenant_id, media.id, "normalize")
    async with tenant_scoped_session(tenant_id) as db:
        job = await db.get(MediaJob, job_id)
        job.cancel_requested = True
        await db.commit()

    assert await _run(env, tenant_id) == "cancelled"

    media, job = await _reload(tenant_id, media.id, job_id)
    assert job.status == "cancelled" and job.error == "cancelled"
    assert media.status == "failed"


async def test_worker_stop_releases_job_without_consuming_attempt(env, tenant_id):
    media = await _media(tenant_id, env, "s.mov", status="processing")
    job_id = await _enqueue(tenant_id, media.id, "normalize")
    stop = asyncio.Event()
    stop.set()

    assert await _run(env, tenant_id, stop=stop) == "queued"

    media, job = await _reload(tenant_id, media.id, job_id)
    assert job.status == "queued" and job.attempts == 0 and job.worker_id is None
    assert job.error == "worker_stopped"
    assert media.status == "processing"


async def test_unknown_kind_and_missing_source_fail_finally(env, tenant_id):
    media = await _media(tenant_id, env, "m.mov", status="processing")
    # `analyze` появится в инкременте 6 — пока вид без обработчика.
    job_id = await _enqueue(tenant_id, media.id, "analyze")
    assert await _run(env, tenant_id) == "failed"
    _, job = await _reload(tenant_id, media.id, job_id)
    assert job.status == "failed" and job.error.startswith("kind_not_implemented")

    media2 = await _media(tenant_id, env, "gone.mov", status="processing")
    job2 = await _enqueue(tenant_id, media2.id, "normalize")
    if FFMPEG is None:
        return
    assert await _run(env, tenant_id) == "failed"
    media2, job = await _reload(tenant_id, media2.id, job2)
    assert job.error.startswith("source_missing") and media2.status == "failed"


async def test_host_lock_busy_means_no_claim(env, tenant_id):
    media = await _media(tenant_id, env, "l.mov", status="processing")
    await _enqueue(tenant_id, media.id, "normalize")
    other = storage.HostLock(env.media_host_lock_path)
    assert other.acquire()
    try:
        assert await _run(env, tenant_id) is None
    finally:
        other.release()
    async with tenant_scoped_session(tenant_id) as db:
        statuses = (
            (await db.execute(select(MediaJob.status).where(MediaJob.media_id == media.id)))
            .scalars()
            .all()
        )
    assert statuses == ["queued"]
