"""Медиа API (Ф3a): загрузка (author+) и отдача по подписанным URL (без JWT).

GET /media/{id} авторизуется ПОДПИСЬЮ (выдана авторизованному юзеру с
проверкой видимости контента) — теги <video>/<img> не умеют Bearer.
Чтение media_files идёт под bypass_rls (нет tenant-контекста без JWT);
запись — только через авторизованный upload.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.course import MediaFile
from app.services.content_access import require_content_role
from app.services.learn_media import (
    MEDIA_MIME_KINDS,
    absolute_path,
    check_free_space,
    media_size_limit,
    mp4_has_faststart,
    sign_media_path,
    storage_key_for_media,
    verify_media_signature,
)
from app.services.learn_settings import get_settings_dict

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

    storage_key, sanitized = storage_key_for_media(
        principal.tenant_id, media.id, file.filename
    )
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
    media.file_name = sanitized
    media.size_bytes = written
    await db.commit()
    return {
        "id": str(media.id),
        "kind": kind,
        "file_name": sanitized,
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
        return FileResponse(path, media_type=media.mime, filename=media.file_name)

    # nginx сам отдаст файл (Range/206, sendfile) по internal-локации.
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/_protected_media/{media.storage_key}",
            "Content-Type": media.mime,
            "Content-Disposition": f'inline; filename="{media.file_name}"',
            "Cache-Control": "private, max-age=3600",
        },
    )
