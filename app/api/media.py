"""Медиа API (Ф3a): загрузка (author+) и отдача по подписанным URL (без JWT).

GET /media/{id} авторизуется ПОДПИСЬЮ (выдана авторизованному юзеру с
проверкой видимости контента) — теги <video>/<img> не умеют Bearer.
Чтение media_files идёт под bypass_rls (нет tenant-контекста без JWT);
запись — только через авторизованный upload.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.course import MediaFile
from app.models.media import MEDIA_ROLES, MediaJob, MediaPart, MediaStoryboard, MediaTranscript
from app.models.progress import LessonProgress
from app.schemas.media import (
    CleanupDefaults,
    CleanupOverrides,
    ComposeEstimateIn,
    ComposeEstimateOut,
    DerivedMediaOut,
    JobCreate,
    MediaAdminSettingsOut,
    MediaAdminSettingsPut,
    MediaCapabilities,
    MediaDetailOut,
    MediaJobOut,
    MediaPartOut,
    MergeCreate,
    MergeOut,
    RetakeOut,
    RetakesOut,
    SceneTestOut,
    StoryboardOut,
    StoryboardParams,
    StoryboardPut,
    TranscriptInfo,
    TranscriptOut,
    UsageLessonOut,
    UsageOut,
)
from app.services import audit, course_index
from app.services.attachments import (
    SNIFF_HEAD_BYTES,
    content_disposition,
    display_filename,
    download_filename,
    resolve_mime,
    sniff_mismatch,
)
from app.services.content_access import require_content_role
from app.services.learn_media import (
    MEDIA_MIME_KINDS,
    absolute_path,
    check_free_space,
    media_size_limit,
    mp4_duration_seconds,
    mp4_has_faststart,
    sign_media_path,
    storage_key_for_media,
    verify_media_signature,
)
from app.services.learn_settings import get_settings_dict, set_setting
from app.services.media import avatar_limit, compose_plan, lesson_media
from app.services.media import gate as media_gate
from app.services.media import jobs as media_jobs
from app.services.media import retakes as retake_rules
from app.services.media import storyboard as storyboard_rules
from app.services.media.autostart import maybe_enqueue_transcribe
from app.services.media.images import aspect_ok, image_size_of
from app.services.media.storage import derived_storage_key
from app.services.media.transcription.base import transcript_gaps
from app.services.timefmt import display_tz

router = APIRouter(tags=["learn-media"])


# Форматы, которые принимаются ТОЛЬКО при включённом конвейере (0066): их
# приводит к MP4 задание `normalize`, пока строка стоит в `processing`.
PIPELINE_VIDEO_MIMES: frozenset[str] = frozenset({"video/quicktime", "video/webm"})
_UPLOAD_CHUNK = 1024 * 1024


def _write_chunk(fh, chunk: bytes) -> None:
    fh.write(chunk)


@router.post("/learn/media", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    role: str = Form("content"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Загрузка медиа урока. При включённом конвейере видео (0066): MOV и WebM
    принимаются, MP4 без faststart не отвергается — всё это уходит в
    `normalize` со статусом `processing` (ответ без `url`); `role` — что это за
    загрузка (`content` по умолчанию; `part`/`insert`/`scene` — только при
    включённом конвейере). Выключено — прежние 415/422."""
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    await require_content_role(db, principal, "author")
    if role not in MEDIA_ROLES:
        raise HTTPException(status_code=422, detail=f"Неизвестная роль файла: {role!r}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла обязательно")

    mime = resolve_mime(file.content_type, file.filename)
    pipeline_on = await media_gate.pipeline_enabled_for(db, principal.tenant_id)
    kind = MEDIA_MIME_KINDS.get(mime)
    if kind is None and pipeline_on and mime in PIPELINE_VIDEO_MIMES:
        kind = "video"
    if kind is None:
        hint = "Видео — MP4, MOV или WebM." if pipeline_on else "Видео — только MP4 (H.264)."
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип {mime!r} не поддерживается. {hint}",
        )
    if role != "content":
        if not pipeline_on:
            raise HTTPException(status_code=422, detail="Конвейер видео выключен")
        if role == "scene" and kind != "image":
            raise HTTPException(status_code=422, detail="Сцена гуся — это картинка")
        if role in ("part", "insert") and kind != "video":
            raise HTTPException(status_code=422, detail="Часть сборки и вставка — это видео")

    settings = get_settings()
    if check_free_space() < settings.media_min_free_bytes:
        # Диск общий с Postgres — не даём загрузке добить его (ревью §17).
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="На сервере мало места — загрузка временно недоступна, сообщите администратору",
        )
    learn_settings = await get_settings_dict(db, principal.tenant_id)
    max_bytes = media_size_limit(kind, learn_settings)

    media = MediaFile(
        tenant_id=principal.tenant_id,
        kind=kind,
        role=role,
        storage_key="",  # заполним после генерации имени
        file_name="",
        mime=mime,
        size_bytes=0,
        uploaded_by=principal.employee_id,
    )
    db.add(media)
    await db.flush()

    storage_key, sanitized = storage_key_for_media(principal.tenant_id, media.id, file.filename)
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    head = b""
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                if not head:
                    head = chunk[:SNIFF_HEAD_BYTES]
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл больше лимита {max_bytes // (1024 * 1024)} МБ",
                    )
                # Запись — в поток: гигабайтный MOV в event loop'е задержал бы
                # остальные запросы на время каждого куска.
                await asyncio.to_thread(_write_chunk, fh, chunk)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл") from exc

    if sniff_mismatch(mime, head):
        dest.unlink(missing_ok=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Содержимое файла не соответствует заявленному типу",
        )

    needs_normalize = False
    if kind == "video":
        needs_normalize = mime != "video/mp4" or not mp4_has_faststart(dest)
        if needs_normalize and not pipeline_on:
            dest.unlink(missing_ok=True)
            await db.rollback()
            raise HTTPException(
                status_code=422,
                detail=(
                    "MP4 без faststart — на телефонах видео не начнёт играть, пока не "
                    "скачается целиком. Пересохраните с «web optimized»/faststart "
                    "(HandBrake: Web Optimized; ffmpeg: -movflags +faststart)."
                ),
            )

    media.storage_key = storage_key
    # В колонку — ЧИТАЕМОЕ имя: ASCII-санитайзер нужен только пути, а от
    # кириллического имени он оставлял одно расширение (ОС 14.09).
    media.file_name = display_filename(file.filename or sanitized)
    media.size_bytes = written
    job: MediaJob | None = None
    transcribe_job_id: str | None = None
    if kind == "video":
        if needs_normalize:
            # Файл НА МЕСТЕ приведёт к MP4 воркер; до `ready` его никто не видит
            # (отдача — 409, в урок не публикуется).
            media.status = "processing"
            media.duration_sec = None
            job = await media_jobs.enqueue(
                db,
                tenant_id=principal.tenant_id,
                media_id=media.id,
                kind="normalize",
                params={"mime": mime},
                requested_by=principal.employee_id,
            )
        else:
            # Длительность читаем СЕРВЕРОМ (0043): гейт досмотра делит на неё, а
            # клиентскому числу верить нельзя. None (битый moov) — не ошибка
            # загрузки: гейт откатится на значение из block_state.
            media.duration_sec = mp4_duration_seconds(dest)
            await db.flush()
            transcribe = await maybe_enqueue_transcribe(
                db, tenant_id=principal.tenant_id, media=media, requested_by=principal.employee_id
            )
            if transcribe is not None:
                transcribe_job_id = str(transcribe.id)
    await db.commit()
    return {
        "id": str(media.id),
        "kind": kind,
        "role": role,
        "status": media.status,
        "file_name": media.file_name,
        "mime": mime,
        "size_bytes": written,
        "duration_sec": media.duration_sec,
        "url": sign_media_path(media.id) if media.status == "ready" else None,
        "normalize_job_id": str(job.id) if job is not None else None,
        "transcribe_job_id": transcribe_job_id,
    }


@router.get("/media/{media_id}")
async def serve_media(
    media_id: UUID,
    e: int = Query(...),
    s: str = Query(..., max_length=64),
) -> Response:
    if not verify_media_signature(media_id, e, s):
        raise HTTPException(status_code=403, detail="Ссылка недействительна или истекла")

    async with tenant_scoped_session(None, bypass_rls=True) as session:
        media = await session.get(MediaFile, media_id)
    if media is None or not media.storage_key:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if media.status != "ready":
        # Нормализация/сборка идёт прямо в этом файле — отдавать его нельзя.
        raise HTTPException(status_code=409, detail="Файл ещё обрабатывается")

    path = absolute_path(media.storage_key)
    settings = get_settings()
    if not settings.media_accel_enabled:
        if not path.is_file():
            raise HTTPException(status_code=410, detail="Файл отсутствует в хранилище")
        # inline, не attachment: PDF/картинки рендерятся в <iframe>/<img>
        # (filename= без content_disposition_type даёт attachment).
        return FileResponse(
            path,
            media_type=media.mime,
            filename=download_filename(media.file_name, mime=media.mime, fallback="файл"),
            content_disposition_type="inline",
        )

    # nginx сам отдаст файл (Range/206, sendfile) по internal-локации.
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/_protected_media/{media.storage_key}",
            "Content-Type": media.mime,
            # Заголовок собираем САМИ, значит и кодируем сами: кириллица,
            # вписанная в filename="…", роняет ответ в latin-1 (500).
            "Content-Disposition": content_disposition(
                download_filename(media.file_name, mime=media.mime, fallback="файл")
            ),
            "Cache-Control": "private, max-age=3600",
        },
    )


# ─── Конвейер видео (0066): настройки тенанта ────────────────────────────────
# ВАЖНО: эти маршруты объявлены раньше любого будущего `/learn/media/{media_id}`
# — иначе «admin» уйдёт в UUID-параметр и ответит 422 вместо настроек.

_ADMIN = require_auth(roles=["admin"])
_PIPELINE_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")

# поле PUT → ключ learning_settings
_SETTING_KEYS: dict[str, str] = {
    "enabled": "media_pipeline_enabled",
    "auto_transcribe": "media_auto_transcribe",
    "scene_media_id": "media_scene_media_id",
    "avatar_monthly_minutes_cap": "media_avatar_monthly_minutes_cap",
    "avatar_resolution": "media_avatar_resolution",
    "cleanup_defaults": "media_cleanup_defaults",
    "storyboard": "media_storyboard",
    "glossary": "media_glossary",
}


def _month_start() -> datetime:
    now = datetime.now(display_tz())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _admin_settings_out(db: AsyncSession, tenant_id: UUID) -> MediaAdminSettingsOut:
    s = await get_settings_dict(db, tenant_id)
    scene_raw = s.get("media_scene_media_id")
    scene_id = UUID(str(scene_raw)) if scene_raw else None
    used_sec = await media_jobs.monthly_avatar_seconds(db, month_start=_month_start())
    return MediaAdminSettingsOut(
        enabled=bool(s.get("media_pipeline_enabled", False)),
        env_enabled=True,
        avatar_env_enabled=media_gate.avatar_env_enabled(),
        stt_configured=media_gate.stt_configured(),
        auto_transcribe=bool(s.get("media_auto_transcribe", True)),
        scene_media_id=scene_id,
        scene_url=sign_media_path(scene_id) if scene_id else None,
        scene_test=await _scene_test(db, scene_id),
        avatar_monthly_minutes_cap=int(s.get("media_avatar_monthly_minutes_cap", 30)),
        avatar_resolution=str(s.get("media_avatar_resolution", "720p")),  # type: ignore[arg-type]
        cleanup_defaults=CleanupDefaults(**(s.get("media_cleanup_defaults") or {})),
        storyboard=StoryboardParams(**(s.get("media_storyboard") or {})),
        glossary=str(s.get("media_glossary") or ""),
        stt_provider=get_settings().media_stt_provider,
        month_used_minutes=round(used_sec / 60, 1),
        active_jobs=await media_jobs.count_active(db),
    )


async def _scene_test(db: AsyncSession, scene_id: UUID | None) -> SceneTestOut | None:
    """Последняя проверка гуся на 10 секундах для этой сцены."""
    if scene_id is None:
        return None
    clip = (
        await db.execute(
            select(MediaFile)
            .where(
                MediaFile.kind == "video",
                MediaFile.role == "scene",
                MediaFile.source_media_id == scene_id,
                MediaFile.status == "ready",
            )
            .order_by(MediaFile.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if clip is None:
        return None
    return SceneTestOut(media_id=clip.id, url=sign_media_path(clip.id), created_at=clip.created_at)


async def _validate_scene(db: AsyncSession, media_id: UUID) -> None:
    """Сцена гуся: картинка своего тенанта, готовая, 16:9 ±5 % (Hedra оживляет
    картинку целиком, и именно этот кадр встанет вместо спикера)."""
    media = await db.get(MediaFile, media_id)
    if media is None or media.kind != "image":
        raise HTTPException(status_code=422, detail="Сцена гуся должна быть картинкой")
    if media.status != "ready":
        raise HTTPException(status_code=422, detail="Картинка ещё обрабатывается")
    try:
        size = image_size_of(absolute_path(media.storage_key))
    except OSError:
        raise HTTPException(status_code=422, detail="Файл сцены не найден на сервере") from None
    if size is not None and not aspect_ok(size):
        raise HTTPException(
            status_code=422,
            detail=f"Нужна сцена 16:9 — у картинки {size[0]}×{size[1]}",
        )


@router.get("/learn/media/admin/settings", response_model=MediaAdminSettingsOut)
async def get_media_admin_settings(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> MediaAdminSettingsOut:
    if not media_gate.env_enabled():
        raise _PIPELINE_NOT_FOUND
    return await _admin_settings_out(db, principal.tenant_id)


@router.put("/learn/media/admin/settings", response_model=MediaAdminSettingsOut)
async def put_media_admin_settings(
    body: MediaAdminSettingsPut,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> MediaAdminSettingsOut:
    """Частичное обновление по ключам; каждое изменение — строка аудита.

    Тумблер тенанта живёт здесь всегда (пока env включён): иначе включить
    модуль неоткуда. Выключение ничего не удаляет — очередь просто перестаёт
    принимать задания, а готовые файлы остаются.
    """
    if not media_gate.env_enabled():
        raise _PIPELINE_NOT_FOUND
    changes = body.model_dump(exclude_unset=True)
    if "scene_media_id" in changes and changes["scene_media_id"] is not None:
        await _validate_scene(db, changes["scene_media_id"])
    current = await get_settings_dict(db, principal.tenant_id)
    diff: dict[str, dict[str, object]] = {}
    for field, value in changes.items():
        key = _SETTING_KEYS[field]
        stored = str(value) if isinstance(value, UUID) else value
        old = current.get(key)
        if old == stored:
            continue
        await set_setting(db, principal.tenant_id, key, stored)
        diff[field] = {"old": old, "new": stored}
    if diff:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="media_settings",
            object_label="Конвейер видео",
            diff=diff,
        )
        await db.commit()
    return await _admin_settings_out(db, principal.tenant_id)


@router.post("/learn/media/admin/avatar-test", response_model=MediaJobOut, status_code=201)
async def start_avatar_test(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> MediaJobOut:
    """«Проверить на 10 секундах»: один запрос Hedra по текущей сцене. Минуты
    резервируются как у монтажа; без сцены или гуся — 409."""
    if not media_gate.env_enabled():
        raise _PIPELINE_NOT_FOUND
    if not await media_gate.avatar_enabled_for(db, principal.tenant_id):
        raise HTTPException(
            status_code=409, detail="Гусь выключен: нет ключа Hedra или модуль выключен"
        )
    s = await get_settings_dict(db, principal.tenant_id)
    scene_raw = s.get("media_scene_media_id")
    if not scene_raw:
        raise HTTPException(status_code=409, detail="Сначала загрузите сцену гуся 16:9")
    scene_id = UUID(str(scene_raw))
    await _validate_scene(db, scene_id)
    try:
        await avatar_limit.reserve(db, principal.tenant_id, need_seconds=10)
    except avatar_limit.AvatarLimitExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    try:
        job = await media_jobs.enqueue(
            db,
            tenant_id=principal.tenant_id,
            media_id=scene_id,
            kind="avatar_test",
            params={
                "estimated_seconds": 10,
                "resolution": str(s.get("media_avatar_resolution", "720p")),
            },
            requested_by=principal.employee_id,
        )
    except media_jobs.JobConflict:
        raise HTTPException(status_code=409, detail="Проверка уже идёт") from None
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="media_job",
        object_id=job.id,
        object_label="Проверка гуся на 10 секундах",
        diff={"estimated_seconds": 10},
    )
    await db.commit()
    return _job_out(job)


# ─── Конвейер видео (0066): сборка из записей, деталь медиа, задания ─────────


async def _require_pipeline(db: AsyncSession, tenant_id: UUID) -> None:
    if not await media_gate.pipeline_enabled_for(db, tenant_id):
        raise _PIPELINE_NOT_FOUND


def _job_out(job: MediaJob) -> MediaJobOut:
    return MediaJobOut(
        id=job.id,
        media_id=job.media_id,
        kind=job.kind,
        status=job.status,
        params=dict(job.params or {}),
        result=dict(job.result or {}),
        error=job.error,
        attempts=job.attempts,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _url_if_ready(media: MediaFile) -> str | None:
    return sign_media_path(media.id) if media.status == "ready" else None


async def _media_detail(db: AsyncSession, media: MediaFile) -> MediaDetailOut:
    part_rows = (
        await db.execute(
            select(MediaPart, MediaFile)
            .join(MediaFile, MediaFile.id == MediaPart.source_media_id)
            .where(MediaPart.merged_media_id == media.id)
            .order_by(MediaPart.position)
        )
    ).all()
    derived = list(
        (
            await db.execute(
                select(MediaFile)
                .where(MediaFile.source_media_id == media.id)
                .order_by(MediaFile.created_at)
            )
        )
        .scalars()
        .all()
    )
    job_rows = await media_jobs.list_for_media(db, [media.id, *(d.id for d in derived)])
    transcript = (
        await db.execute(
            select(
                MediaTranscript.language,
                MediaTranscript.provider,
                MediaTranscript.model,
                MediaTranscript.updated_at,
                func.length(MediaTranscript.text),
            ).where(MediaTranscript.media_id == media.id)
        )
    ).one_or_none()
    # У монтажа своих субтитров нет — дорожка чистовика по цепочке
    # (`lesson_media.subtitle_ids`, одно правило с отдачей урока).
    subtitle_id = (await lesson_media.subtitle_ids(db, [media.id])).get(media.id)
    storyboard_row = await db.get(MediaStoryboard, media.id)
    return MediaDetailOut(
        id=media.id,
        kind=media.kind,
        role=media.role,
        status=media.status,
        file_name=media.file_name,
        mime=media.mime,
        size_bytes=media.size_bytes,
        duration_sec=media.duration_sec,
        url=_url_if_ready(media),
        variant=media.variant,
        source_media_id=media.source_media_id,
        created_at=media.created_at,
        parts=[
            MediaPartOut(
                position=part.position,
                source_media_id=source.id,
                trim_start_sec=float(part.trim_start_sec or 0.0),
                trim_end_sec=part.trim_end_sec,
                file_name=source.file_name,
                duration_sec=source.duration_sec,
                status=source.status,
            )
            for part, source in part_rows
        ],
        derived=[
            DerivedMediaOut(
                id=d.id,
                kind=d.kind,
                variant=d.variant,
                status=d.status,
                url=_url_if_ready(d),
                duration_sec=d.duration_sec,
                size_bytes=d.size_bytes,
                file_name=d.file_name,
                created_at=d.created_at,
            )
            for d in derived
        ],
        jobs=[_job_out(j) for j in job_rows],
        capabilities=MediaCapabilities(
            transcribe=media.kind == "video"
            and media.status == "ready"
            and media_gate.stt_configured(),
            # Чистовик — по готовому видео с транскриптом (без STT — по тишине).
            cleanup=media.kind == "video"
            and media.status == "ready"
            and (transcript is not None or not media_gate.stt_configured()),
            # Монтаж — по чистовику с раскадровкой.
            compose=media.kind == "video"
            and media.status == "ready"
            and media.variant == "cleaned"
            and storyboard_row is not None,
        ),
        transcript=TranscriptInfo(
            language=transcript[0],
            provider=transcript[1],
            model=transcript[2],
            updated_at=transcript[3],
            chars=int(transcript[4] or 0),
        )
        if transcript is not None
        else None,
        subtitle_url=sign_media_path(subtitle_id) if subtitle_id is not None else None,
    )


@router.post("/learn/media/merge", status_code=201, response_model=MergeOut)
async def merge_media(
    body: MergeCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MergeOut:
    """«5 записей → одно видео»: создаёт собранный файл в `processing`,
    строки `media_parts` и задание `merge`. Все части — `role='part'` своего
    тенанта и `ready`; иначе 409 с номером части (клиент повторит, когда
    конвертация части доедет)."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    ids = [p.media_id for p in body.parts]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Одна и та же запись указана дважды")
    rows = {
        m.id: m
        for m in (await db.execute(select(MediaFile).where(MediaFile.id.in_(ids)))).scalars()
    }
    for i, part in enumerate(body.parts, start=1):
        m = rows.get(part.media_id)
        if m is None or m.kind != "video":
            raise HTTPException(status_code=422, detail=f"Часть {i}: это не видео")
        if m.role != "part":
            raise HTTPException(
                status_code=422, detail=f"Часть {i}: файл загружен не как часть сборки"
            )
        if m.status == "processing":
            raise HTTPException(status_code=409, detail=f"Часть {i} ещё конвертируется — подождите")
        if m.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Часть {i}: конвертация не удалась, загрузите файл заново",
            )
        start_sec, end_sec = part.trim_start_sec, part.trim_end_sec
        if end_sec is not None and end_sec <= start_sec:
            raise HTTPException(status_code=422, detail=f"Часть {i}: «до» раньше, чем «с»")
        if m.duration_sec:
            if start_sec >= m.duration_sec:
                raise HTTPException(
                    status_code=422, detail=f"Часть {i}: начало подрезки за концом записи"
                )
            if end_sec is not None and end_sec > m.duration_sec + 0.5:
                raise HTTPException(
                    status_code=422, detail=f"Часть {i}: конец подрезки за концом записи"
                )

    first = rows[ids[0]]
    merged = MediaFile(
        tenant_id=principal.tenant_id,
        kind="video",
        role="content",
        status="processing",
        storage_key="",
        file_name=f"{Path(first.file_name).stem or 'Видео'} — сборка.mp4"[:255],
        mime="video/mp4",
        size_bytes=0,
        uploaded_by=principal.employee_id,
    )
    db.add(merged)
    await db.flush()
    merged.storage_key = derived_storage_key(principal.tenant_id, merged.id, "merged.mp4")
    for position, part in enumerate(body.parts):
        db.add(
            MediaPart(
                merged_media_id=merged.id,
                position=position,
                tenant_id=principal.tenant_id,
                source_media_id=part.media_id,
                trim_start_sec=part.trim_start_sec,
                trim_end_sec=part.trim_end_sec,
            )
        )
    await db.flush()
    job = await media_jobs.enqueue(
        db,
        tenant_id=principal.tenant_id,
        media_id=merged.id,
        kind="merge",
        params={
            "parts": [
                {
                    "media_id": str(p.media_id),
                    "trim_start_sec": p.trim_start_sec,
                    "trim_end_sec": p.trim_end_sec,
                }
                for p in body.parts
            ]
        },
        requested_by=principal.employee_id,
    )
    await db.commit()
    return MergeOut(media=await _media_detail(db, merged), job=_job_out(job))


@router.get("/learn/media/jobs/{job_id}", response_model=MediaJobOut)
async def get_media_job(
    job_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MediaJobOut:
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    job = await db.get(MediaJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return _job_out(job)


@router.post("/learn/media/jobs/{job_id}/cancel", response_model=MediaJobOut, status_code=202)
async def cancel_media_job(
    job_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MediaJobOut:
    """`queued` → `cancelled` сразу; `running` — флаг, воркер остановит ffmpeg
    на ближайшем heartbeat (≤ 30 с). Завершённое задание не меняется."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    job = await db.get(MediaJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    new_status = await media_jobs.cancel(db, job)
    if new_status == "cancelled" and job.kind in ("normalize", "merge"):
        # Файл не дождётся обработки — строка не должна висеть в processing.
        media = await db.get(MediaFile, job.media_id)
        if media is not None and media.status == "processing":
            media.status = "failed"
    await db.commit()
    return _job_out(job)


@router.post("/learn/media/{media_id}/jobs", status_code=201, response_model=MediaJobOut)
async def create_media_job(
    media_id: UUID,
    body: JobCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MediaJobOut:
    """Запуск или повтор задания по кнопке. Предусловия проверяет API (очередь
    без DAG): `transcribe` — готовое видео и настроенная расшифровка;
    дубликат активного — 409 «уже выполняется»."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if media.kind != "video":
        raise HTTPException(status_code=409, detail="Задание ставится только на видео")
    if media.status != "ready":
        raise HTTPException(status_code=409, detail="Файл ещё обрабатывается")
    params: dict = dict(body.params or {})
    if body.kind == "transcribe" and not media_gate.stt_configured():
        raise HTTPException(
            status_code=409,
            detail="Расшифровка не настроена на сервере — сообщите администратору",
        )
    if body.kind == "cleanup":
        try:
            params = CleanupOverrides(**params).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc.errors()[0]["msg"])) from None
        has_transcript = await db.get(MediaTranscript, media.id) is not None
        if not has_transcript and media_gate.stt_configured():
            raise HTTPException(
                status_code=409,
                detail="Сначала дождитесь расшифровки — паузы ищутся по тексту и звуку",
            )
        cuts = params.get("cuts")
        if cuts is not None and media.duration_sec:
            limit = float(media.duration_sec) + 0.5
            if any(float(c["e"]) > limit for c in cuts):
                raise HTTPException(status_code=422, detail="Вырезка выходит за длительность видео")
    if body.kind == "compose":
        if media.variant != "cleaned":
            raise HTTPException(status_code=409, detail="Монтаж собирается по готовому чистовику")
        estimate, plan = await _compose_estimate(
            db, principal.tenant_id, media, params.get("resolution")
        )
        if not estimate.allowed:
            raise HTTPException(status_code=409, detail=estimate.reason or "Монтаж недоступен")
        if plan.chunks:
            # Гусь — publisher и выше (решение владельца): это платно.
            await require_content_role(db, principal, "publisher")
            try:
                await avatar_limit.reserve(
                    db, principal.tenant_id, need_seconds=plan.billed_seconds
                )
            except avatar_limit.AvatarLimitExceeded as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from None
        params = {
            **params,
            "resolution": estimate.resolution,
            "goose_enabled": plan.goose_enabled,
            "chunks": [list(c) for c in plan.chunks],
            "inserts": plan.inserts,
            "estimated_seconds": plan.billed_seconds,
            "estimated_cost_cents": plan.cost_cents,
        }
    try:
        job = await media_jobs.enqueue(
            db,
            tenant_id=principal.tenant_id,
            media_id=media.id,
            kind=body.kind,
            params=params,
            requested_by=principal.employee_id,
        )
    except media_jobs.JobConflict:
        raise HTTPException(status_code=409, detail="Уже выполняется") from None
    if body.kind == "compose":
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="create",
            object_type="media_job",
            object_id=job.id,
            object_label=f"Монтаж: {media.file_name}",
            diff={
                "estimated_seconds": params["estimated_seconds"],
                "estimated_cost_cents": params["estimated_cost_cents"],
            },
        )
    await db.commit()
    return _job_out(job)


@router.get("/learn/media/{media_id}/transcript", response_model=TranscriptOut)
async def get_media_transcript(
    media_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TranscriptOut:
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    row = await db.get(MediaTranscript, media_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Расшифровки ещё нет")
    return TranscriptOut(
        language=row.language,
        chars=len(row.text),
        provider=row.provider,
        model=row.model,
        updated_at=row.updated_at,
        text=row.text,
        segments=list(row.segments or []),
        duration_sec=row.duration_sec,
    )


def _storyboard_out(row: MediaStoryboard, duration: float | None) -> StoryboardOut:
    return StoryboardOut(
        media_id=row.media_id,
        duration_sec=duration,
        face_track=list(row.face_track or []),
        segments_auto=list(row.segments_auto or []),
        segments=list(row.segments or []),
        inserts=list(row.inserts or []),
        goose_enabled=bool(row.goose_enabled),
        edited_by=row.edited_by,
        params=dict(row.params or {}),
        updated_at=row.updated_at,
    )


async def _compose_estimate(
    db: AsyncSession, tenant_id: UUID, media: MediaFile, resolution_override: str | None
) -> tuple[ComposeEstimateOut, compose_plan.ComposePlan]:
    board = await db.get(MediaStoryboard, media.id)
    if board is None:
        raise HTTPException(status_code=409, detail="Сначала дождитесь раскадровки чистовика")
    s = await get_settings_dict(db, tenant_id)
    resolution = str(resolution_override or s.get("media_avatar_resolution", "720p"))
    transcript = await db.get(MediaTranscript, media.id)
    duration = float(media.duration_sec or 0.0)
    gaps = transcript_gaps(transcript.segments, duration) if transcript and duration else []
    try:
        plan = compose_plan.plan_compose(
            duration=duration,
            segments=list(board.segments or []),
            inserts=list(board.inserts or []),
            goose_enabled=bool(board.goose_enabled),
            resolution=resolution,
            transcript_gaps=gaps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    cap, used = await avatar_limit.month_usage(db, tenant_id)
    scene_set = bool(s.get("media_scene_media_id"))
    reason: str | None = None
    if not plan.chunks and not plan.inserts:
        reason = "Нечего монтировать: ни отрезков гуся, ни вставок"
    elif plan.chunks:
        if not await media_gate.avatar_enabled_for(db, tenant_id):
            reason = "Гусь выключен на сервере"
        elif not scene_set:
            reason = "Сначала загрузите сцену гуся в «Управление → Видео»"
        elif used + plan.billed_seconds > cap * 60:
            reason = f"Лимит минут гуся на месяц исчерпан: занято {used / 60:.1f} из {cap}"
    return (
        ComposeEstimateOut(
            goose_enabled=plan.goose_enabled,
            resolution=resolution,  # type: ignore[arg-type]
            goose_seconds=round(plan.goose_seconds, 2),
            segments=len(board.segments or []),
            inserts=len(plan.inserts),
            chunks=len(plan.chunks),
            billed_seconds=plan.billed_seconds,
            cost_cents=plan.cost_cents,
            monthly_cap_sec=cap * 60,
            monthly_used_sec=round(used, 1),
            allowed=reason is None,
            reason=reason,
            scene_set=scene_set,
        ),
        plan,
    )


@router.post("/learn/media/{media_id}/compose/estimate", response_model=ComposeEstimateOut)
async def compose_estimate(
    media_id: UUID,
    body: ComposeEstimateIn,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ComposeEstimateOut:
    """Оценка монтажа по действующей раскадровке: секунды гуся (минус
    вставки), куски, цена по локальной таблице, остаток лимита."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if media.variant != "cleaned" or media.status != "ready":
        raise HTTPException(status_code=409, detail="Монтаж собирается по готовому чистовику")
    out, _plan = await _compose_estimate(db, principal.tenant_id, media, body.resolution)
    return out


@router.get("/learn/media/{media_id}/storyboard", response_model=StoryboardOut)
async def get_storyboard(
    media_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StoryboardOut:
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    row = await db.get(MediaStoryboard, media_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Раскадровки ещё нет")
    return _storyboard_out(row, media.duration_sec)


@router.put("/learn/media/{media_id}/storyboard", response_model=StoryboardOut)
async def put_storyboard(
    media_id: UUID,
    body: StoryboardPut,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StoryboardOut:
    """Правка автора: границы отрезков и режим `goose|keep` у спикера, вставки
    поверх голоса, тумблер гуся. Правила — `services/media/storyboard.py`
    (покрытие без дыр, вставки без пересечений); пока идёт `compose` — 409."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    row = await db.get(MediaStoryboard, media_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Раскадровки ещё нет")
    if await media_jobs.active_job(db, media_id, "compose") is not None:
        raise HTTPException(status_code=409, detail="Идёт монтаж — дождитесь его окончания")
    duration = float(media.duration_sec or 0.0)
    if body.segments is not None:
        try:
            row.segments = storyboard_rules.validate_segments(
                [seg.model_dump(exclude_none=True) for seg in body.segments], duration=duration
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    if body.inserts is not None:
        raw = [
            {"media_id": str(i.media_id), "at": i.at, "duration": i.duration} for i in body.inserts
        ]
        try:
            inserts = storyboard_rules.validate_inserts(raw, duration=duration)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        ids = {UUID(i["media_id"]) for i in inserts}
        if ids:
            rows = (
                (await db.execute(select(MediaFile).where(MediaFile.id.in_(ids)))).scalars().all()
            )
            found = {m.id: m for m in rows}
            for mid in ids:
                m = found.get(mid)
                if m is None or m.kind != "video" or m.role != "insert":
                    raise HTTPException(
                        status_code=422, detail="Вставка должна быть видео, загруженным как вставка"
                    )
                if m.status != "ready":
                    raise HTTPException(status_code=409, detail="Вставка ещё конвертируется")
        row.inserts = inserts
    if body.goose_enabled is not None:
        row.goose_enabled = body.goose_enabled
    row.edited_by = principal.employee_id
    await db.commit()
    await db.refresh(row)
    return _storyboard_out(row, media.duration_sec)


@router.get("/learn/media/{media_id}/usage", response_model=UsageOut)
async def get_media_usage(
    media_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    """В каких уроках стоит это видео и сколько человек сейчас его проходят —
    для предупреждения при замене оригинала чистовиком (прогресс просмотра у
    них сбросится)."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    rows = (await db.execute(course_index.lessons_referencing_media_stmt(media_id))).all()
    out: list[UsageLessonOut] = []
    key = str(media_id).lower()
    for lesson, course in rows:
        in_progress = (
            await db.execute(
                select(func.count())
                .select_from(LessonProgress)
                .where(
                    LessonProgress.lesson_id == lesson.id,
                    LessonProgress.status != "completed",
                    LessonProgress.block_state["video"].has_key(key),
                )
            )
        ).scalar_one()
        out.append(
            UsageLessonOut(
                lesson_id=lesson.id,
                title=lesson.title,
                course_id=course.id,
                course_title=course.title,
                published=lesson.status == "published" and course.status == "published",
                in_progress=int(in_progress or 0),
            )
        )
    return UsageOut(lessons=out)


@router.get("/learn/media/{media_id}/retakes", response_model=RetakesOut)
async def get_media_retakes(
    media_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> RetakesOut:
    """Кандидаты на вырезку перезаписей по транскрипту исходника — для списка
    с тумблерами во вкладке «Чистовик» до заказа. Чистая функция над
    транскриптом, считается на лету."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if media.kind != "video":
        raise HTTPException(status_code=409, detail="Перезаписи ищутся только у видео")
    transcript = await db.get(MediaTranscript, media.id)
    duration = float(media.duration_sec or (transcript.duration_sec if transcript else 0) or 0)
    items = (
        retake_rules.find_retakes(list(transcript.segments or []), duration=duration)
        if transcript is not None and duration > 0
        else []
    )
    return RetakesOut(
        media_id=media.id,
        duration_sec=media.duration_sec,
        transcript=transcript is not None,
        items=[RetakeOut(**r.to_json()) for r in items],
    )


@router.get("/learn/media/{media_id}", response_model=MediaDetailOut)
async def get_media_detail(
    media_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MediaDetailOut:
    """Состояние файла для редактора: статус, части сборки, производные,
    последние задания, что можно заказать. Опрашивается, пока идёт работа."""
    await _require_pipeline(db, principal.tenant_id)
    await require_content_role(db, principal, "author")
    media = await db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return await _media_detail(db, media)
