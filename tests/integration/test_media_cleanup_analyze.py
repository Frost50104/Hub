"""Чистовик и раскадровка (инкремент 6) на живой БД и ffmpeg: `cleanup` даёт
новую строку `variant='cleaned'` с перемапленным транскриптом и VTT и ставит
`analyze`; `analyze` пишет раскадровку (на тест-таблице лиц нет — один
отрезок «экран»); ручки раскадровки и использования; предусловия заказа."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.media import (
    create_media_job,
    get_media_detail,
    get_media_retakes,
    get_media_usage,
    get_storyboard,
    put_storyboard,
)
from app.config import get_settings
from app.models.course import Course, CourseLesson, MediaFile
from app.models.media import MediaJob, MediaStoryboard, MediaTranscript
from app.models.progress import LessonProgress
from app.schemas.media import JobCreate, StoryboardInsertIn, StoryboardPut, StoryboardSegmentIn
from app.services.media import gate, jobs, storage
from app.workers import media as worker
from tests.integration.conftest import make_principal
from tests.integration.test_courses import _mk_member
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


def _gen(path: Path, *, dur: float = 6.0) -> None:
    # Синус 1–2,5 с и 4–6 с, цифровая тишина 2,5–4 с: одна пауза 1,5 с.
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
            f"testsrc=duration={dur}:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='if(between(t,2.5,4),0,0.4*sin(440*2*PI*t))':s=48000:d={dur}",
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
    principal = make_principal(tenant_id, role="admin", tenant_slug=f"cl-{uuid.uuid4().hex[:8]}")
    await _register(db, principal)
    await gate.set_tenant_enabled(db, tenant_id, True)
    await db.commit()
    return principal


async def _video(
    db, tenant_id, env, src: Path | None, *, name="Запись.mp4", duration=6.0
) -> MediaFile:
    media = MediaFile(
        tenant_id=tenant_id,
        kind="video",
        role="content",
        status="ready",
        storage_key="",
        file_name=name,
        mime="video/mp4",
        size_bytes=1,
        duration_sec=duration,
    )
    db.add(media)
    await db.flush()
    media.storage_key = f"{tenant_id}/learn/media/{media.id}-rec.mp4"
    dest = Path(env.attachments_root) / media.storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        shutil.copy(src, dest)
    return media


SEGMENTS = [
    {
        "s": 1.0,
        "e": 2.4,
        "t": "Добрый день, коллеги",
        "w": [[1.0, 1.6, "Добрый"], [1.6, 2.4, "день"]],
    },
    {"s": 4.2, "e": 5.8, "t": "Нажимаем Сохранить"},
]


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
async def test_cleanup_then_analyze(db, tenant_id, env, tmp_path):
    admin = await _admin(db, tenant_id)
    src = tmp_path / "src.mp4"
    _gen(src)
    media = await _video(db, tenant_id, env, src)
    db.add(
        MediaTranscript(
            media_id=media.id,
            tenant_id=tenant_id,
            provider="fake",
            model="m",
            language="ru",
            text="Добрый день, коллеги Нажимаем Сохранить",
            segments=SEGMENTS,
            duration_sec=6.0,
        )
    )
    await db.flush()
    job = await create_media_job(
        media.id, JobCreate(kind="cleanup", params={"min_pause_sec": 1.0}), admin, db
    )
    assert job.kind == "cleanup" and job.params == {"min_pause_sec": 1.0}

    assert await _run(env, tenant_id) == "done"

    await db.refresh(media)
    row = await db.get(MediaJob, job.id)
    await db.refresh(row)
    assert row.status == "done", row.error
    stats = row.result["stats"]
    # Пауза — зазор между словами 2,4–4,2 (синус затихает на 2,5–4,0, края
    # громкие на 17 % времени) → ужата до 0,7 с.
    assert stats["pauses"] == 1 and stats["removed_sec"] == pytest.approx(1.1, abs=0.2)
    assert stats["retakes"] == 0 and row.result["retakes"] == []
    assert row.result["speech_level_db"] is not None and row.result["threshold_db"] <= -30
    assert row.result["pauses"][0]["context"] == "после «Добрый день»"
    assert row.result["loudnorm"] and "input_i" in row.result["loudnorm"]
    cleaned = await db.get(MediaFile, row.output_media_id)
    assert cleaned.variant == "cleaned" and cleaned.source_media_id == media.id
    assert cleaned.file_name == "Запись — чистовик.mp4" and cleaned.status == "ready"
    assert cleaned.duration_sec == pytest.approx(6.0 - stats["removed_sec"], abs=0.3)
    assert (Path(env.attachments_root) / cleaned.storage_key).exists()
    tr = await db.get(MediaTranscript, cleaned.id)
    assert tr.source_transcript_media_id == media.id
    assert tr.segments[1]["s"] == pytest.approx(4.2 - stats["removed_sec"], abs=0.05)
    subs = (
        (
            await db.execute(
                select(MediaFile).where(
                    MediaFile.kind == "subtitle", MediaFile.source_media_id == cleaned.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert (
        len(subs) == 1
        and "WEBVTT" in (Path(env.attachments_root) / subs[0].storage_key).read_text()
    )
    kinds = (
        await db.execute(
            select(MediaJob.kind, MediaJob.status).where(MediaJob.media_id == cleaned.id)
        )
    ).all()
    assert kinds == [("analyze", "queued")]
    detail = await get_media_detail(media.id, admin, db)
    assert [d.variant for d in detail.derived] == ["cleaned"]
    assert detail.capabilities.cleanup is True

    pytest.importorskip("cv2")
    assert await _run(env, tenant_id) == "done"
    sb = await db.get(MediaStoryboard, cleaned.id)
    await db.refresh(sb)
    assert sb.segments == [{"s": 0.0, "e": round(cleaned.duration_sec, 2), "kind": "screen"}]
    assert len(sb.face_track) >= 5 and all(r == 0 for r in sb.face_track)
    out = await get_storyboard(cleaned.id, admin, db)
    assert out.segments == sb.segments and out.edited_by is None
    # Правка автора переживает повторный analyze.
    end = round(cleaned.duration_sec, 2)
    edited = await put_storyboard(
        cleaned.id,
        StoryboardPut(
            segments=[
                StoryboardSegmentIn(s=0, e=2, kind="speaker", mode="keep"),
                StoryboardSegmentIn(s=2, e=end, kind="screen"),
            ],
            goose_enabled=False,
        ),
        admin,
        db,
    )
    assert edited.edited_by == admin.employee_id and edited.goose_enabled is False
    await jobs.enqueue(db, tenant_id=tenant_id, media_id=cleaned.id, kind="analyze")
    await db.commit()
    assert await _run(env, tenant_id) == "done"
    await db.refresh(sb)
    assert sb.segments[0]["kind"] == "speaker" and sb.segments_auto[0]["kind"] == "screen"


async def test_cleanup_preconditions_and_storyboard_validation(db, tenant_id, env):
    admin = await _admin(db, tenant_id)
    media = await _video(db, tenant_id, env, None)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await create_media_job(media.id, JobCreate(kind="cleanup"), admin, db)
    assert exc.value.status_code == 409 and "расшифровки" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await create_media_job(
            media.id, JobCreate(kind="cleanup", params={"min_pause_sec": 99}), admin, db
        )
    assert exc.value.status_code == 422
    # Перезаписи: без транскрипта — пусто; с транскриптом — кандидат по
    # повтору начала фразы; вырезка за пределами длительности — 422.
    empty = await get_media_retakes(media.id, admin, db)
    assert empty.transcript is False and empty.items == []
    db.add(
        MediaTranscript(
            media_id=media.id,
            tenant_id=tenant_id,
            provider="fake",
            model="m",
            language="ru",
            text="Выбираем проект. Стоп. Выбираем проект. У нас появляется список.",
            segments=[
                {
                    "s": 0.0,
                    "e": 1.0,
                    "t": "Выбираем проект.",
                    "w": [[0.0, 0.5, "Выбираем"], [0.5, 1.0, "проект."]],
                },
                {"s": 1.5, "e": 1.9, "t": "Стоп.", "w": [[1.5, 1.9, "Стоп."]]},
                {
                    "s": 3.0,
                    "e": 5.5,
                    "t": "Выбираем проект. У нас появляется список.",
                    "w": [
                        [3.0, 3.5, "Выбираем"],
                        [3.5, 4.0, "проект."],
                        [4.0, 4.3, "У"],
                        [4.3, 4.6, "нас"],
                        [4.6, 5.0, "появляется"],
                        [5.0, 5.5, "список."],
                    ],
                },
            ],
            duration_sec=6.0,
        )
    )
    await db.flush()
    found = await get_media_retakes(media.id, admin, db)
    assert found.transcript is True and len(found.items) == 1
    assert found.items[0].reason == "marker" and found.items[0].confidence == "high"
    assert found.items[0].s == pytest.approx(0.0) and found.items[0].e == pytest.approx(2.92)
    with pytest.raises(HTTPException) as exc:
        await create_media_job(
            media.id, JobCreate(kind="cleanup", params={"cuts": [{"s": 1, "e": 9}]}), admin, db
        )
    assert exc.value.status_code == 422 and "длительность" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await create_media_job(
            media.id, JobCreate(kind="cleanup", params={"cuts": [{"s": 2, "e": 1}]}), admin, db
        )
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await get_storyboard(media.id, admin, db)
    assert exc.value.status_code == 404
    db.add(
        MediaStoryboard(
            media_id=media.id,
            tenant_id=tenant_id,
            segments=[{"s": 0, "e": 6, "kind": "screen"}],
            segments_auto=[],
            face_track=[],
        )
    )
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await put_storyboard(
            media.id,
            StoryboardPut(segments=[StoryboardSegmentIn(s=0, e=3, kind="screen")]),
            admin,
            db,
        )
    assert exc.value.status_code == 422 and "до конца" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await put_storyboard(
            media.id,
            StoryboardPut(inserts=[StoryboardInsertIn(media_id=uuid.uuid4(), at=1, duration=2)]),
            admin,
            db,
        )
    assert exc.value.status_code == 422
    insert = MediaFile(
        tenant_id=tenant_id,
        kind="video",
        role="insert",
        status="ready",
        storage_key="x",
        file_name="i.mp4",
        mime="video/mp4",
        size_bytes=1,
        duration_sec=2,
    )
    db.add(insert)
    await db.flush()
    out = await put_storyboard(
        media.id,
        StoryboardPut(inserts=[StoryboardInsertIn(media_id=insert.id, at=1, duration=9)]),
        admin,
        db,
    )
    assert out.inserts == [{"media_id": str(insert.id), "at": 1.0, "duration": 5.0}]


async def test_usage_counts_lessons_and_people_in_progress(db, tenant_id, env):
    admin = await _admin(db, tenant_id)
    media = await _video(db, tenant_id, env, None)
    _, profile = await _mk_member(db, tenant_id, email=f"s-{uuid.uuid4().hex[:6]}@t.ru")
    course = Course(
        tenant_id=tenant_id, title="Сервис", progression_mode="free", status="published"
    )
    db.add(course)
    await db.flush()
    doc = {
        "schema": 1,
        "doc": {"type": "doc", "content": [{"type": "video", "attrs": {"mediaId": str(media.id)}}]},
    }
    lesson = CourseLesson(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Урок",
        position=0,
        content_format="blocks",
        content=doc,
        status="published",
    )
    draft = CourseLesson(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Черновик",
        position=1,
        content_format="blocks",
        content=doc,
        status="draft",
    )
    db.add_all([lesson, draft])
    await db.flush()
    db.add(
        LessonProgress(
            profile_id=profile.id,
            lesson_id=lesson.id,
            tenant_id=tenant_id,
            course_id=course.id,
            status="in_progress",
            block_state={"video": {str(media.id).lower(): {"intervals": [[0, 1]]}}},
        )
    )
    await db.flush()
    out = await get_media_usage(media.id, admin, db)
    rows = {u.title: u for u in out.lessons}
    assert set(rows) == {"Урок", "Черновик"}
    assert rows["Урок"].published is True and rows["Урок"].in_progress == 1
    assert rows["Черновик"].published is False and rows["Черновик"].in_progress == 0
    assert (await get_media_usage(uuid.uuid4(), admin, db)).lessons == []
