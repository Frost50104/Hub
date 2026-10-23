"""Расшифровка (0066, инкремент 4) на живой БД: задание `transcribe` с фейковым
провайдером → транскрипт + VTT + документ урока в поиске; урок отдаёт
`trackSrc`/`status`; публикация с необработанным видео — 409; автозапуск
после нормализации; ручки запуска и чтения расшифровки."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.courses import get_lesson, update_lesson
from app.api.media import create_media_job, get_media_detail, get_media_transcript
from app.config import get_settings
from app.models.course import Course, CourseLesson, MediaFile
from app.models.media import MediaJob, MediaTranscript
from app.models.search_document import SearchDocument
from app.schemas.course import LessonUpdate
from app.schemas.media import JobCreate
from app.services.media import gate, jobs, storage
from app.services.media.pipeline import transcribe_job
from app.services.media.transcription.base import Segment, TranscriptResult, Word
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
    monkeypatch.setenv("SIGNARIS_HUB_MEDIA_STT_URL", "http://127.0.0.1:1")
    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "attachments_root", tmp_path)
    monkeypatch.setattr(s, "media_min_free_bytes", 0)
    monkeypatch.setattr(s, "media_host_lock_path", tmp_path / "media.lock")
    yield s
    get_settings.cache_clear()


class FakeProvider:
    name = "fake"
    model = "fake-1"
    calls = 0

    async def transcribe_file(
        self,
        wav_path,
        *,
        language,
        glossary,
        beam_size,
        duration,
        silences,
        on_chunk=None,
        cancel=None,
    ):
        FakeProvider.calls += 1
        assert wav_path.exists() and language == "ru"
        self.glossary = glossary
        if on_chunk is not None:
            await on_chunk(1, 1)
        return TranscriptResult(
            segments=[
                Segment(0.2, 1.4, "Добро пожаловать в Hub", words=[Word(0.2, 0.8, "Добро")]),
                Segment(1.6, 2.8, "Сегодня про стандарты сервиса"),
            ],
            language="ru",
            duration_sec=duration,
            provider="fake",
            model="fake-1",
        )


@pytest.fixture
def fake_provider(monkeypatch):
    FakeProvider.calls = 0
    monkeypatch.setattr(transcribe_job, "get_provider", lambda _settings: FakeProvider())
    return FakeProvider


def _gen_mp4(path: Path, *, dur: float = 3.0, fps: int = 30) -> None:
    subprocess.run(  # noqa: S603
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
            f"testsrc=duration={dur}:size=320x240:rate={fps}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={dur}:sample_rate=48000",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(path),
        ],
        check=True,
    )


async def _admin(db, tenant_id):
    principal = make_principal(tenant_id, role="admin", tenant_slug=f"tr-{uuid.uuid4().hex[:8]}")
    await _register(db, principal)
    await gate.set_tenant_enabled(db, tenant_id, True)
    await db.commit()
    return principal


async def _video(
    db, tenant_id, env, name="Вебинар.mp4", *, status="ready", src: Path | None = None
):
    media = MediaFile(
        tenant_id=tenant_id,
        kind="video",
        role="content",
        status=status,
        storage_key="",
        file_name=name,
        mime="video/mp4",
        size_bytes=1,
        duration_sec=3.0,
    )
    db.add(media)
    await db.flush()
    media.storage_key = f"{tenant_id}/learn/media/{media.id}-webinar.mp4"
    dest = Path(env.attachments_root) / media.storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        shutil.copy(src, dest)
    return media


def _doc(media_id) -> dict:
    return {
        "schema": 1,
        "doc": {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Смотрим запись"}]},
                {
                    "type": "video",
                    "attrs": {
                        "mediaId": str(media_id),
                        "src": None,
                        "requireFullWatch": False,
                        "disableSeek": False,
                    },
                },
            ],
        },
    }


async def _course_with_lesson(db, tenant_id, media_id, *, lesson_status="published"):
    course = Course(
        tenant_id=tenant_id, title="Стандарты сервиса", progression_mode="free", status="published"
    )
    db.add(course)
    await db.flush()
    lesson = CourseLesson(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Вводный вебинар",
        position=0,
        content_format="blocks",
        content=_doc(media_id),
        status=lesson_status,
    )
    db.add(lesson)
    await db.flush()
    return course, lesson


async def _run(env, tenant_id) -> str | None:
    return await worker.run_once(
        settings=env,
        stop=asyncio.Event(),
        lock=storage.HostLock(env.media_host_lock_path),
        worker_id="t",
        heartbeat_sec=0.2,
        tenant_id=tenant_id,
    )


@needs_ffmpeg
async def test_transcribe_job_writes_transcript_vtt_and_lesson_document(
    db, tenant_id, env, fake_provider, tmp_path
):
    admin = await _admin(db, tenant_id)
    src = tmp_path / "src.mp4"
    _gen_mp4(src)
    media = await _video(db, tenant_id, env, src=src)
    course, lesson = await _course_with_lesson(db, tenant_id, media.id)
    job = await jobs.enqueue(db, tenant_id=tenant_id, media_id=media.id, kind="transcribe")
    await db.commit()

    assert await _run(env, tenant_id) == "done"

    await db.refresh(job)
    assert job.status == "done"
    assert job.result["segments"] == 2 and job.result["provider"] == "fake"
    assert job.result["lessons_indexed"] == 1
    transcript = await db.get(MediaTranscript, media.id)
    assert transcript.text == "Добро пожаловать в Hub Сегодня про стандарты сервиса"
    assert transcript.segments[0]["w"] == [[0.2, 0.8, "Добро"]]
    assert (transcript.provider, transcript.model, transcript.language) == ("fake", "fake-1", "ru")
    subs = (
        (
            await db.execute(
                select(MediaFile).where(
                    MediaFile.kind == "subtitle", MediaFile.source_media_id == media.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(subs) == 1
    sub = subs[0]
    assert job.output_media_id == sub.id
    assert sub.mime == "text/vtt" and sub.status == "ready" and sub.file_name == "Вебинар.vtt"
    vtt = (Path(env.attachments_root) / sub.storage_key).read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "Добро пожаловать в Hub" in vtt
    doc = (
        await db.execute(
            select(SearchDocument).where(
                SearchDocument.object_type == "course_lesson", SearchDocument.object_id == lesson.id
            )
        )
    ).scalar_one()
    assert doc.published_at is None  # не в «Новинках»
    assert doc.title == "Стандарты сервиса · Вводный вебинар"
    assert "стандарты сервиса" in doc.body_text
    assert doc.url_path == f"/learn/lessons/{lesson.id}"

    # Урок отдаёт дорожку субтитров и статус видео.
    out = await get_lesson(lesson.id, admin, db)
    node = out.content["doc"]["content"][1]["attrs"]
    assert node["trackSrc"].startswith(f"/api/media/{sub.id}?") and node["status"] == "ready"
    assert node["src"].startswith(f"/api/media/{media.id}?")

    # Деталь медиа: сводка расшифровки и субтитры; ручка транскрипта.
    detail = await get_media_detail(media.id, admin, db)
    assert detail.transcript.chars == len(transcript.text) and detail.transcript.provider == "fake"
    assert detail.subtitle_url.startswith(f"/api/media/{sub.id}?")
    assert [d.kind for d in detail.derived] == ["subtitle"]
    full = await get_media_transcript(media.id, admin, db)
    assert full.text == transcript.text and len(full.segments) == 2

    # Повтор переписывает тот же VTT, а не плодит строки.
    await jobs.enqueue(db, tenant_id=tenant_id, media_id=media.id, kind="transcribe")
    await db.commit()
    assert await _run(env, tenant_id) == "done"
    subs = (
        (
            await db.execute(
                select(MediaFile).where(
                    MediaFile.kind == "subtitle", MediaFile.source_media_id == media.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(subs) == 1 and fake_provider.calls == 2

    # Снятие урока с публикации убирает документ; возврат — возвращает.
    await update_lesson(lesson.id, LessonUpdate(status="draft"), admin, db)
    assert (
        await db.execute(select(SearchDocument).where(SearchDocument.object_id == lesson.id))
    ).scalar_one_or_none() is None
    await update_lesson(lesson.id, LessonUpdate(status="published"), admin, db)
    assert (
        await db.execute(select(SearchDocument).where(SearchDocument.object_id == lesson.id))
    ).scalar_one() is not None


async def test_publish_is_blocked_while_video_is_processing(db, tenant_id, env):
    admin = await _admin(db, tenant_id)
    media = await _video(db, tenant_id, env, status="processing")
    course, lesson = await _course_with_lesson(db, tenant_id, media.id, lesson_status="draft")
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await update_lesson(lesson.id, LessonUpdate(status="published"), admin, db)
    assert exc.value.status_code == 409 and "конвертации" in exc.value.detail
    # Без смены статуса правки проходят.
    await update_lesson(lesson.id, LessonUpdate(title="Черновик"), admin, db)
    # Менеджер видит черновик: нода без src и со статусом.
    out = await get_lesson(lesson.id, admin, db)
    node = out.content["doc"]["content"][1]["attrs"]
    assert node["src"] is None and node["status"] == "processing" and node["trackSrc"] is None


@needs_ffmpeg
async def test_normalize_done_autostarts_transcribe(db, tenant_id, env, tmp_path):
    await _admin(db, tenant_id)
    src = tmp_path / "clip.mov"
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
            "testsrc=duration=2:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-f",
            "mov",
            str(src),
        ],
        check=True,
    )
    media = await _video(db, tenant_id, env, "clip.mov", status="processing", src=src)
    await jobs.enqueue(db, tenant_id=tenant_id, media_id=media.id, kind="normalize")
    await db.commit()

    assert await _run(env, tenant_id) == "done"

    kinds = (
        await db.execute(
            select(MediaJob.kind, MediaJob.status)
            .where(MediaJob.media_id == media.id)
            .order_by(MediaJob.created_at)
        )
    ).all()
    assert kinds == [("normalize", "done"), ("transcribe", "queued")]


async def test_create_job_endpoint_preconditions(db, tenant_id, env, monkeypatch):
    admin = await _admin(db, tenant_id)
    pending = await _video(db, tenant_id, env, status="processing")
    ready = await _video(db, tenant_id, env)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await create_media_job(pending.id, JobCreate(kind="transcribe"), admin, db)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await get_media_transcript(ready.id, admin, db)
    assert exc.value.status_code == 404
    job = await create_media_job(ready.id, JobCreate(kind="transcribe"), admin, db)
    assert job.kind == "transcribe" and job.status == "queued"
    with pytest.raises(HTTPException) as exc:
        await create_media_job(ready.id, JobCreate(kind="transcribe"), admin, db)
    assert exc.value.status_code == 409 and "выполняется" in exc.value.detail
    monkeypatch.setattr(gate, "stt_configured", lambda: False)
    other = await _video(db, tenant_id, env)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await create_media_job(other.id, JobCreate(kind="transcribe"), admin, db)
    assert exc.value.status_code == 409 and "не настроена" in exc.value.detail
    with pytest.raises(ValueError):
        JobCreate(kind="compose")
