"""Загрузка при включённом конвейере (0066): MOV/WebM и MP4 без faststart →
`processing` + задание `normalize`; роли файла; сниффер; сборка из записей;
деталь медиа; отмена задания; отдача 409, пока файл обрабатывается."""

from __future__ import annotations

import io
import struct
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.api.media import (
    cancel_media_job,
    get_media_detail,
    merge_media,
    serve_media,
    upload_media,
)
from app.config import get_settings
from app.models.course import MediaFile
from app.models.media import MediaJob, MediaPart
from app.schemas.media import MergeCreate, MergePart
from app.services.learn_media import issue_token
from app.services.media import gate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


FTYP = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
MP4_FAST = FTYP + _box(b"moov", b"\x00" * 16) + _box(b"mdat", b"\x00" * 64)
MP4_SLOW = FTYP + _box(b"mdat", b"\x00" * 64) + _box(b"moov", b"\x00" * 16)
MOV = _box(b"ftyp", b"qt  \x00\x00\x02\x00qt  ") + _box(b"mdat", b"\x00" * 64)
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 60
PNG = (
    b"\x89PNG\r\n\x1a\n"
    + struct.pack(">I", 13)
    + b"IHDR"
    + struct.pack(">II", 16, 9)
    + b"\x00" * 60
)


def _upload(data: bytes, name: str, mime: str | None) -> UploadFile:
    headers = {"content-type": mime} if mime else {}
    return UploadFile(file=io.BytesIO(data), size=len(data), filename=name, headers=headers)


@pytest.fixture
def pipeline_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED", "true")
    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "attachments_root", tmp_path)
    monkeypatch.setattr(s, "media_min_free_bytes", 0)
    monkeypatch.setattr(s, "media_accel_enabled", True)
    yield tmp_path
    get_settings.cache_clear()


async def _admin(db, tenant_id, *, pipeline: bool = True):
    principal = make_principal(tenant_id, role="admin", tenant_slug=f"m-{uuid.uuid4().hex[:8]}")
    await _register(db, principal)
    if pipeline:
        await gate.set_tenant_enabled(db, tenant_id, True)
    await db.commit()
    return principal


async def _job(db, job_id) -> MediaJob:
    return (
        await db.execute(select(MediaJob).where(MediaJob.id == uuid.UUID(str(job_id))))
    ).scalar_one()


async def test_mov_goes_to_processing_with_normalize_job(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    out = await upload_media(_upload(MOV, "Запись.mov", "video/quicktime"), "content", admin, db)
    assert out["status"] == "processing" and out["url"] is None and out["duration_sec"] is None
    assert out["kind"] == "video" and out["role"] == "content" and out["mime"] == "video/quicktime"
    job = await _job(db, out["normalize_job_id"])
    assert (job.kind, job.status, job.priority) == ("normalize", "queued", 10)
    assert job.params == {"mime": "video/quicktime"}
    media = await db.get(MediaFile, uuid.UUID(out["id"]))
    assert media.status == "processing"
    # Кириллическое имя санитайзер режет до `-mov` — на диске файл именно там.
    assert media.storage_key.endswith("-mov") and media.file_name == "Запись.mov"
    assert (pipeline_env / media.storage_key).read_bytes() == MOV
    # Пока обрабатывается — отдача 409, не битый файл.
    exp, sig = issue_token(str(media.id), 600)
    with pytest.raises(HTTPException) as exc:
        await serve_media(media.id, exp, sig)
    assert exc.value.status_code == 409


async def test_webm_and_slow_mp4_also_normalize(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    out = await upload_media(_upload(WEBM, "cam.webm", "video/webm"), "content", admin, db)
    assert out["status"] == "processing"
    out = await upload_media(_upload(MP4_SLOW, "slow.mp4", "video/mp4"), "content", admin, db)
    assert out["status"] == "processing" and out["normalize_job_id"]
    out = await upload_media(_upload(MP4_FAST, "fast.mp4", "video/mp4"), "content", admin, db)
    assert out["status"] == "ready" and out["url"] and out["normalize_job_id"] is None


async def test_pipeline_off_keeps_old_behaviour(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id, pipeline=False)
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(MOV, "a.mov", "video/quicktime"), "content", admin, db)
    assert exc.value.status_code == 415 and "только MP4" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(MP4_SLOW, "slow.mp4", "video/mp4"), "content", admin, db)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(MP4_FAST, "a.mp4", "video/mp4"), "part", admin, db)
    assert exc.value.status_code == 422 and "выключен" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await get_media_detail(uuid.uuid4(), admin, db)
    assert exc.value.status_code == 404


async def test_roles_and_sniffer(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    out = await upload_media(_upload(MP4_FAST, "p.mp4", "video/mp4"), "part", admin, db)
    assert out["role"] == "part"
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(MP4_FAST, "p.mp4", "video/mp4"), "scene", admin, db)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(PNG, "s.png", "image/png"), "insert", admin, db)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(PNG, "s.png", "image/png"), "banner", admin, db)
    assert exc.value.status_code == 422
    scene = await upload_media(_upload(PNG, "s.png", "image/png"), "scene", admin, db)
    assert scene["role"] == "scene" and scene["status"] == "ready"
    # PNG под именем видео — 415 по магическим байтам.
    with pytest.raises(HTTPException) as exc:
        await upload_media(_upload(PNG, "fake.mp4", "video/mp4"), "content", admin, db)
    assert exc.value.status_code == 415
    # octet-stream восстанавливается по расширению.
    out = await upload_media(
        _upload(MOV, "cam.MOV", "application/octet-stream"), "content", admin, db
    )
    assert out["mime"] == "video/quicktime" and out["status"] == "processing"


async def _part(
    db, tenant_id, name: str, *, status="ready", role="part", duration=10.0
) -> MediaFile:
    media = MediaFile(
        tenant_id=tenant_id,
        kind="video",
        role=role,
        status=status,
        storage_key=f"{tenant_id}/learn/media/{uuid.uuid4()}-{name}",
        file_name=name,
        mime="video/mp4",
        size_bytes=1,
        duration_sec=duration,
    )
    db.add(media)
    await db.flush()
    return media


async def test_merge_creates_processing_media_parts_and_job(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    a = await _part(db, tenant_id, "Вебинар 1.mp4")
    b = await _part(db, tenant_id, "Вебинар 2.mp4")
    body = MergeCreate(
        parts=[MergePart(media_id=a.id), MergePart(media_id=b.id, trim_start_sec=1, trim_end_sec=5)]
    )
    out = await merge_media(body, admin, db)
    assert out.media.status == "processing" and out.media.url is None
    assert out.media.file_name == "Вебинар 1 — сборка.mp4"
    assert out.media.storage_key if hasattr(out.media, "storage_key") else True
    assert [
        (p.position, p.source_media_id, p.trim_start_sec, p.trim_end_sec) for p in out.media.parts
    ] == [
        (0, a.id, 0.0, None),
        (1, b.id, 1.0, 5.0),
    ]
    assert out.job.kind == "merge" and out.job.status == "queued"
    assert out.media.jobs[0].id == out.job.id
    assert out.media.capabilities.transcribe is False
    rows = (
        (await db.execute(select(MediaPart).where(MediaPart.merged_media_id == out.media.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    detail = await get_media_detail(out.media.id, admin, db)
    assert detail.parts[1].file_name == "Вебинар 2.mp4" and detail.jobs[0].kind == "merge"


async def test_merge_validations(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    a = await _part(db, tenant_id, "a.mp4")
    pending = await _part(db, tenant_id, "b.mov", status="processing")
    failed = await _part(db, tenant_id, "f.mov", status="failed")
    content = await _part(db, tenant_id, "c.mp4", role="content")

    async def expect(parts, code, text):
        with pytest.raises(HTTPException) as exc:
            await merge_media(MergeCreate(parts=parts), admin, db)
        assert exc.value.status_code == code, exc.value.detail
        assert text in exc.value.detail

    expect_ = expect
    await expect_(
        [MergePart(media_id=a.id), MergePart(media_id=pending.id)],
        409,
        "Часть 2 ещё конвертируется",
    )
    await expect_([MergePart(media_id=failed.id), MergePart(media_id=a.id)], 409, "Часть 1")
    await expect_([MergePart(media_id=a.id), MergePart(media_id=content.id)], 422, "не как часть")
    await expect_([MergePart(media_id=a.id), MergePart(media_id=a.id)], 422, "дважды")
    await expect_([MergePart(media_id=a.id), MergePart(media_id=uuid.uuid4())], 422, "не видео")
    await expect_(
        [MergePart(media_id=a.id, trim_start_sec=12), MergePart(media_id=a.id)], 422, "дважды"
    )
    b = await _part(db, tenant_id, "b2.mp4")
    await expect_(
        [MergePart(media_id=a.id, trim_start_sec=12), MergePart(media_id=b.id)], 422, "за концом"
    )
    await expect_(
        [MergePart(media_id=a.id, trim_end_sec=20), MergePart(media_id=b.id)], 422, "за концом"
    )
    await expect_(
        [MergePart(media_id=a.id, trim_start_sec=5, trim_end_sec=4), MergePart(media_id=b.id)],
        422,
        "раньше",
    )
    with pytest.raises(ValueError):
        MergeCreate(parts=[MergePart(media_id=a.id)])


async def test_cancel_queued_job_marks_media_failed(db, tenant_id, pipeline_env):
    admin = await _admin(db, tenant_id)
    a = await _part(db, tenant_id, "a.mp4")
    b = await _part(db, tenant_id, "b.mp4")
    out = await merge_media(
        MergeCreate(parts=[MergePart(media_id=a.id), MergePart(media_id=b.id)]), admin, db
    )
    cancelled = await cancel_media_job(out.job.id, admin, db)
    assert cancelled.status == "cancelled"
    media = await db.get(MediaFile, out.media.id)
    assert media.status == "failed"
    # Повторная отмена — без изменений, не ошибка.
    assert (await cancel_media_job(out.job.id, admin, db)).status == "cancelled"
    with pytest.raises(HTTPException) as exc:
        await cancel_media_job(uuid.uuid4(), admin, db)
    assert exc.value.status_code == 404
