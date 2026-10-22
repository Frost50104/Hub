"""Видео урока глазами сервера: статусы файлов и дорожки субтитров по
`mediaId` нод — для `prepare_for_consumer` и гейта публикации урока."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import MediaFile
from app.services.learn_media import sign_media_path


async def video_tracks(
    db: AsyncSession, media_ids: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """→ (`{media_id: url субтитров}`, `{media_id: status}`); ключи в нижнем
    регистре, как в `collect_video_ids`. Субтитры — строка `kind='subtitle'`
    с `source_media_id` на видео, готовая; из нескольких берётся свежая."""
    if not media_ids:
        return {}, {}
    ids = [UUID(x) for x in media_ids]
    status_rows = await db.execute(
        select(MediaFile.id, MediaFile.status).where(MediaFile.id.in_(ids))
    )
    statuses = {str(mid).lower(): status for mid, status in status_rows}
    sub_rows = await db.execute(
        select(MediaFile.id, MediaFile.source_media_id)
        .where(
            MediaFile.kind == "subtitle",
            MediaFile.status == "ready",
            MediaFile.source_media_id.in_(ids),
        )
        .order_by(MediaFile.created_at)
    )
    tracks: dict[str, str] = {}
    for sub_id, source_id in sub_rows:
        tracks[str(source_id).lower()] = sign_media_path(sub_id)
    return tracks, statuses


async def videos_not_ready(db: AsyncSession, media_ids: list[str]) -> list[str]:
    """Видео урока, которые ещё обрабатываются или не сконвертировались:
    такой урок публиковать нельзя (сотрудник получил бы плейсхолдер навсегда)."""
    _tracks, statuses = await video_tracks(db, media_ids)
    return [mid for mid, status in statuses.items() if status != "ready"]
