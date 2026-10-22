"""Медиа API (Ф3a): загрузка (author+) и отдача по подписанным URL (без JWT).

GET /media/{id} авторизуется ПОДПИСЬЮ (выдана авторизованному юзеру с
проверкой видимости контента) — теги <video>/<img> не умеют Bearer.
Чтение media_files идёт под bypass_rls (нет tenant-контекста без JWT);
запись — только через авторизованный upload.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.course import MediaFile
from app.schemas.media import (
    CleanupDefaults,
    MediaAdminSettingsOut,
    MediaAdminSettingsPut,
    StoryboardParams,
)
from app.services import audit
from app.services.attachments import (
    content_disposition,
    display_filename,
    download_filename,
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
from app.services.media import gate as media_gate
from app.services.media import jobs as media_jobs
from app.services.media.images import aspect_ok, image_size_of
from app.services.timefmt import display_tz

router = APIRouter(tags=["learn-media"])


@router.post("/learn/media", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    await require_content_role(db, principal, "author")

    mime = file.content_type or "application/octet-stream"
    kind = MEDIA_MIME_KINDS.get(mime)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип {mime!r} не поддерживается. Видео — только MP4 (H.264).",
        )
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла обязательно")

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
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл больше лимита {max_bytes // (1024 * 1024)} МБ",
                    )
                fh.write(chunk)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл") from exc

    if kind == "video" and not mp4_has_faststart(dest):
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
    if kind == "video":
        # Длительность читаем СЕРВЕРОМ (0043): гейт досмотра делит на неё, а
        # клиентскому числу верить нельзя. None (битый moov) — не ошибка
        # загрузки: гейт откатится на значение из block_state.
        media.duration_sec = mp4_duration_seconds(dest)
    await db.commit()
    return {
        "id": str(media.id),
        "kind": kind,
        "file_name": media.file_name,
        "mime": mime,
        "size_bytes": written,
        "url": sign_media_path(media.id),
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
        # Появится вместе с заданием `avatar_test` (инкремент 7).
        scene_test=None,
        avatar_monthly_minutes_cap=int(s.get("media_avatar_monthly_minutes_cap", 30)),
        avatar_resolution=str(s.get("media_avatar_resolution", "720p")),  # type: ignore[arg-type]
        cleanup_defaults=CleanupDefaults(**(s.get("media_cleanup_defaults") or {})),
        storyboard=StoryboardParams(**(s.get("media_storyboard") or {})),
        glossary=str(s.get("media_glossary") or ""),
        stt_provider=get_settings().media_stt_provider,
        month_used_minutes=round(used_sec / 60, 1),
        active_jobs=await media_jobs.count_active(db),
    )


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
