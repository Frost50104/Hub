"""Автозапуск расшифровки, когда видео урока стало `ready`: после прямой
загрузки MP4, после `normalize`, после `merge`. Только контент урока
(`role='content'`), только при включённом конвейере тенанта, его настройке
`media_auto_transcribe` и настроенном STT; повторно не ставится, если
транскрипт уже есть (перезапуск — кнопкой, `POST /learn/media/{id}/jobs`)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import MediaFile
from app.models.media import MediaJob, MediaTranscript
from app.services.learn_settings import get_settings_dict
from app.services.media import gate, jobs


async def maybe_enqueue_transcribe(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    media: MediaFile,
    requested_by: UUID | None = None,
) -> MediaJob | None:
    if media.kind != "video" or media.status != "ready" or media.role != "content":
        return None
    if not gate.env_enabled() or not gate.stt_configured():
        return None
    settings = await get_settings_dict(db, tenant_id)
    if not settings.get("media_pipeline_enabled", False):
        return None
    if not settings.get("media_auto_transcribe", True):
        return None
    has_transcript = (
        await db.execute(
            select(MediaTranscript.media_id).where(MediaTranscript.media_id == media.id)
        )
    ).scalar_one_or_none()
    if has_transcript is not None:
        return None
    try:
        return await jobs.enqueue(
            db,
            tenant_id=tenant_id,
            media_id=media.id,
            kind="transcribe",
            requested_by=requested_by,
        )
    except jobs.JobConflict:
        return None
