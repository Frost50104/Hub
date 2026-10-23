"""Монтаж (инкремент 7) с фейковой Hedra на MockTransport: оценка, заказ с
резервом минут и аудитом, задание `compose` (голос → submit → поллинг →
скачивание → склейка), возобновление по `params.hedra_state` без второго
submit, провал модерации возвращает минуты, `avatar_test` админки."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.media import (
    compose_estimate,
    create_media_job,
    get_media_admin_settings,
    get_media_detail,
    start_avatar_test,
)
from app.config import get_settings
from app.models.audit import AuditLog
from app.models.course import MediaFile
from app.models.media import MediaJob, MediaStoryboard, MediaTranscript
from app.schemas.media import ComposeEstimateIn, JobCreate
from app.services.learn_settings import set_setting
from app.services.media import gate, lesson_media, storage
from app.services.media.hedra.client import HedraClient
from app.services.media.pipeline import avatar_test_job, compose_job
from app.workers import media as worker
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="нет ffmpeg")


@pytest.fixture(autouse=True)
def _engine_per_test(_fresh_engine):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_AVATAR_ENABLED", "true")
    monkeypatch.setenv("SIGNARIS_HUB_HEDRA_API_KEY", "k_test")
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_STT_URL", "http://127.0.0.1:1")
    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "attachments_root", tmp_path)
    monkeypatch.setattr(s, "media_min_free_bytes", 0)
    monkeypatch.setattr(s, "media_host_lock_path", tmp_path / "media.lock")
    monkeypatch.setattr(s, "hedra_poll_sec", 0.01)
    yield s
    get_settings.cache_clear()


class FakeHedra:
    """Сервер Hedra в памяти: файлы, задания, результат — клип ffmpeg."""

    def __init__(self, clip: Path, *, fail_submit: int | None = None) -> None:
        self.clip = clip
        self.fail_submit = fail_submit
        self.submits: list[dict] = []
        self.uploads = 0
        self.polls: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v3/files":
            self.uploads += 1
            return httpx.Response(200, json={"id": f"file_{self.uploads}"})
        if path == "/v3/models/hedra-character-3":
            body = json.loads(request.content)
            self.submits.append(body)
            if self.fail_submit is not None and self.fail_submit == len(self.submits):
                return httpx.Response(422, text="MODERATION_FAILED")
            return httpx.Response(202, json={"id": f"gen_{len(self.submits)}", "status": "queued"})
        if path.startswith("/v3/jobs/") and path.endswith("/status"):
            job_id = path.split("/")[3]
            self.polls[job_id] = self.polls.get(job_id, 0) + 1
            status = "complete" if self.polls[job_id] >= 2 else "processing"
            return httpx.Response(200, json={"id": job_id, "status": status, "progress": 0.5})
        if path.startswith("/v3/jobs/"):
            job_id = path.split("/")[3]
            return httpx.Response(
                200,
                json={
                    "id": job_id,
                    "status": "complete",
                    "outputs": [{"url": f"https://cdn.test/{job_id}.mp4"}],
                    "cost": 0.5,
                },
            )
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=self.clip.read_bytes())
        return httpx.Response(404)


def _gen(
    path: Path, *, dur: float, size: str = "320x240", audio: bool = True, fmt: str | None = None
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
        f"testsrc=duration={dur}:size={size}:rate=30",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=48000"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-ac", "2", "-shortest"]
    cmd += ["-movflags", "+faststart"]
    if fmt:
        cmd += ["-f", fmt]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)  # noqa: S603


async def _admin(db, tenant_id):
    principal = make_principal(tenant_id, role="admin", tenant_slug=f"cm-{uuid.uuid4().hex[:8]}")
    await _register(db, principal)
    await gate.set_tenant_enabled(db, tenant_id, True)
    await db.commit()
    return principal


async def _media(db, tenant_id, env, src: Path | None, **kw) -> MediaFile:
    fields = dict(
        kind="video",
        role="content",
        status="ready",
        storage_key="",
        file_name="Запись — чистовик.mp4",
        mime="video/mp4",
        size_bytes=1,
        duration_sec=12.0,
        variant="cleaned",
    )
    fields.update(kw)
    media = MediaFile(tenant_id=tenant_id, **fields)
    db.add(media)
    await db.flush()
    media.storage_key = (
        f"{tenant_id}/learn/media/{media.id}-x.{'png' if media.kind == 'image' else 'mp4'}"
    )
    dest = Path(env.attachments_root) / media.storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        shutil.copy(src, dest)
    return media


def _png(path: Path) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",  # noqa: S603
            "color=c=white:s=1920x1080:d=1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )


async def _run(env, tenant_id) -> str | None:
    return await worker.run_once(
        settings=env,
        stop=asyncio.Event(),
        lock=storage.HostLock(env.media_host_lock_path),
        worker_id="t",
        heartbeat_sec=0.2,
        tenant_id=tenant_id,
    )


async def _setup(db, tenant_id, env, tmp_path, *, goose=True):
    admin = await _admin(db, tenant_id)
    src = tmp_path / "cleaned.mp4"
    _gen(src, dur=12.0)
    cleaned = await _media(db, tenant_id, env, src)
    scene_png = tmp_path / "scene.png"
    _png(scene_png)
    scene = await _media(
        db,
        tenant_id,
        env,
        scene_png,
        kind="image",
        role="scene",
        mime="image/png",
        variant=None,
        duration_sec=None,
        file_name="scene.png",
    )
    await set_setting(db, tenant_id, "media_scene_media_id", str(scene.id))
    ins_src = tmp_path / "insert.mp4"
    _gen(ins_src, dur=3.0, size="640x360", audio=False)
    insert = await _media(
        db,
        tenant_id,
        env,
        ins_src,
        role="insert",
        variant=None,
        duration_sec=3.0,
        file_name="insert.mp4",
    )
    db.add(
        MediaTranscript(
            media_id=cleaned.id,
            tenant_id=tenant_id,
            provider="fake",
            model="m",
            language="ru",
            text="x",
            segments=[{"s": 0.5, "e": 5.5, "t": "раз"}, {"s": 6.5, "e": 11.5, "t": "два"}],
            duration_sec=12.0,
        )
    )
    db.add(
        MediaStoryboard(
            media_id=cleaned.id,
            tenant_id=tenant_id,
            face_track=[],
            segments_auto=[],
            segments=[
                {"s": 0, "e": 6, "kind": "speaker", "mode": "goose"},
                {"s": 6, "e": 12, "kind": "screen"},
            ],
            inserts=[{"media_id": str(insert.id), "at": 8, "duration": 3}],
            goose_enabled=goose,
        )
    )
    await db.commit()
    return admin, cleaned, scene, insert


@needs_ffmpeg
async def test_estimate_order_and_compose_with_fake_hedra(
    db, tenant_id, env, tmp_path, monkeypatch
):
    admin, cleaned, scene, insert = await _setup(db, tenant_id, env, tmp_path)
    est = await compose_estimate(cleaned.id, ComposeEstimateIn(), admin, db)
    assert est.allowed and est.goose_seconds == 6.0 and est.chunks == 1 and est.inserts == 1
    assert est.cost_cents == 30 and est.monthly_cap_sec == 30 * 60 and est.scene_set
    cheap = await compose_estimate(cleaned.id, ComposeEstimateIn(resolution="540p"), admin, db)
    assert cheap.cost_cents == 15

    job = await create_media_job(cleaned.id, JobCreate(kind="compose"), admin, db)
    assert job.params["estimated_seconds"] == 6 and job.params["chunks"] == [[0.0, 6.0]]
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.object_type == "media_job")))
        .scalars()
        .all()
    )
    assert len(audit) == 1
    # Резерв виден следующей оценке; дубль — 409.
    est2 = await compose_estimate(cleaned.id, ComposeEstimateIn(), admin, db)
    assert est2.monthly_used_sec == 6.0
    with pytest.raises(HTTPException) as exc:
        await create_media_job(cleaned.id, JobCreate(kind="compose"), admin, db)
    assert exc.value.status_code == 409

    clip = tmp_path / "goose.mp4"
    _gen(clip, dur=6.0, size="1280x720", audio=False)
    fake = FakeHedra(clip)
    monkeypatch.setattr(
        compose_job,
        "_client",
        lambda ctx: HedraClient(api_key="k", transport=httpx.MockTransport(fake.handler)),
    )

    assert await _run(env, tenant_id) == "done"

    row = await db.get(MediaJob, job.id)
    await db.refresh(row)
    assert row.status == "done", row.error
    assert row.result["billed_seconds"] == 6 and row.result["cost_cents"] == 30
    chunk = row.result["hedra"]["chunks"][0]
    assert chunk["job_id"] == "gen_1" and chunk["status"] == "downloaded" and chunk["cost"] == 0.5
    assert chunk["idempotency_key"] == f"{job.id}:0"
    assert fake.submits[0]["input"]["duration_ms"] == 6000 and fake.uploads == 2
    composed = await db.get(MediaFile, row.output_media_id)
    assert composed.variant == "composed" and composed.source_media_id == cleaned.id
    assert composed.file_name == "Запись — монтаж.mp4"
    assert composed.duration_sec == pytest.approx(12.0, abs=0.3)
    assert (Path(env.attachments_root) / composed.storage_key).exists()

    # Субтитры монтажа — дорожка ЧИСТОВИКА по цепочке `source_media_id`:
    # и в детали медиа, и в отдаче урока (`video_tracks`).
    sub = await _media(
        db,
        tenant_id,
        env,
        None,
        kind="subtitle",
        mime="text/vtt",
        variant=None,
        duration_sec=None,
        file_name="Запись.vtt",
        source_media_id=cleaned.id,
    )
    await db.commit()
    detail = await get_media_detail(composed.id, admin, db)
    assert detail.subtitle_url and detail.subtitle_url.startswith(f"/api/media/{sub.id}?")
    tracks, statuses = await lesson_media.video_tracks(db, [str(composed.id), str(cleaned.id)])
    assert tracks[str(composed.id)].startswith(f"/api/media/{sub.id}?")
    assert tracks[str(cleaned.id)].startswith(f"/api/media/{sub.id}?")
    assert statuses[str(composed.id)] == "ready"


@needs_ffmpeg
async def test_compose_resumes_without_second_submit_and_moderation_returns_minutes(
    db, tenant_id, env, tmp_path, monkeypatch
):
    admin, cleaned, scene, insert = await _setup(db, tenant_id, env, tmp_path)
    clip = tmp_path / "goose.mp4"
    _gen(clip, dur=6.0, size="1280x720", audio=False)
    fake = FakeHedra(clip)
    monkeypatch.setattr(
        compose_job,
        "_client",
        lambda ctx: HedraClient(api_key="k", transport=httpx.MockTransport(fake.handler)),
    )
    job = await create_media_job(cleaned.id, JobCreate(kind="compose"), admin, db)
    # Первая попытка «упала» после submit: воркер унёс состояние в params.
    async with __import__("app.db", fromlist=["tenant_scoped_session"]).tenant_scoped_session(
        tenant_id
    ) as s2:
        row = await s2.get(MediaJob, job.id)
        row.params = {
            **row.params,
            "hedra_state": {
                "image_id": "file_1",
                "chunks": [
                    {
                        "i": 0,
                        "segment": [0.0, 6.0],
                        "idempotency_key": f"{job.id}:0",
                        "job_id": "gen_9",
                        "status": "submitted",
                        "duration_ms": 6000,
                        "cost": None,
                    }
                ],
            },
        }
        await s2.commit()
    assert await _run(env, tenant_id) == "done"
    assert fake.submits == []  # второго submit не было
    assert fake.uploads == 0
    row = await db.get(MediaJob, job.id)
    await db.refresh(row)
    assert (
        row.result["hedra"]["chunks"][0]["job_id"] == "gen_9" and row.result["billed_seconds"] == 6
    )

    # Суперпользователь тестов RLS не видит: суммы — по всей БД контейнера,
    # поэтому сравниваем относительно, а не с абсолютом.
    base_used = (
        await compose_estimate(cleaned.id, ComposeEstimateIn(), admin, db)
    ).monthly_used_sec

    # Модерация: финал без второй попытки, минуты возвращаются.
    cleaned2_src = tmp_path / "c2.mp4"
    _gen(cleaned2_src, dur=12.0)
    cleaned2 = await _media(db, tenant_id, env, cleaned2_src)
    db.add(
        MediaStoryboard(
            media_id=cleaned2.id,
            tenant_id=tenant_id,
            face_track=[],
            segments_auto=[],
            segments=[{"s": 0, "e": 12, "kind": "speaker", "mode": "goose"}],
            inserts=[],
            goose_enabled=True,
        )
    )
    await db.commit()
    bad = FakeHedra(clip, fail_submit=1)
    monkeypatch.setattr(
        compose_job,
        "_client",
        lambda ctx: HedraClient(api_key="k", transport=httpx.MockTransport(bad.handler)),
    )
    job2 = await create_media_job(cleaned2.id, JobCreate(kind="compose"), admin, db)
    assert job2.params["estimated_seconds"] == 12
    assert await _run(env, tenant_id) == "failed"
    row2 = await db.get(MediaJob, job2.id)
    await db.refresh(row2)
    assert (
        row2.status == "failed"
        and row2.error.startswith("moderation_failed")
        and row2.attempts == 1
    )
    assert row2.result["billed_seconds"] == 0
    est = await compose_estimate(cleaned2.id, ComposeEstimateIn(), admin, db)
    assert est.monthly_used_sec == base_used  # резерв провалившегося вернулся


@needs_ffmpeg
async def test_limit_blocks_order_and_free_compose_without_goose(db, tenant_id, env, tmp_path):
    admin, cleaned, scene, insert = await _setup(db, tenant_id, env, tmp_path, goose=False)
    est = await compose_estimate(cleaned.id, ComposeEstimateIn(), admin, db)
    assert est.allowed and est.cost_cents == 0 and est.chunks == 0 and est.inserts == 1
    await set_setting(db, tenant_id, "media_avatar_monthly_minutes_cap", 0)
    board = await db.get(MediaStoryboard, cleaned.id)
    board.goose_enabled = True
    await db.commit()
    est = await compose_estimate(cleaned.id, ComposeEstimateIn(), admin, db)
    assert not est.allowed and "Лимит" in (est.reason or "")
    with pytest.raises(HTTPException) as exc:
        await create_media_job(cleaned.id, JobCreate(kind="compose"), admin, db)
    assert exc.value.status_code == 409 and "Лимит" in exc.value.detail


@needs_ffmpeg
async def test_avatar_test_job_and_scene_test_in_settings(
    db, tenant_id, env, tmp_path, monkeypatch
):
    admin, cleaned, scene, insert = await _setup(db, tenant_id, env, tmp_path)
    clip = tmp_path / "goose.mp4"
    _gen(clip, dur=10.0, size="1280x720", audio=False)
    fake = FakeHedra(clip)
    monkeypatch.setattr(
        avatar_test_job,
        "HedraClient",
        lambda **kw: HedraClient(api_key="k", transport=httpx.MockTransport(fake.handler)),
    )
    before = (await get_media_admin_settings(admin, db)).month_used_minutes
    job = await start_avatar_test(admin, db)
    assert (
        job.kind == "avatar_test"
        and job.media_id == scene.id
        and job.params["estimated_seconds"] == 10
    )
    with pytest.raises(HTTPException) as exc:
        await start_avatar_test(admin, db)
    assert exc.value.status_code == 409
    assert await _run(env, tenant_id) == "done"
    row = await db.get(MediaJob, job.id)
    await db.refresh(row)
    assert row.status == "done", row.error
    assert fake.submits[0]["input"]["duration_ms"] == 10000
    settings = await get_media_admin_settings(admin, db)
    assert settings.scene_test is not None and settings.scene_test.media_id == row.output_media_id
    # В ответе минуты округлены до десятых: 6 с → 0,1, 16 с → 0,3.
    assert settings.month_used_minutes - before == pytest.approx(10 / 60, abs=0.1)
