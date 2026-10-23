"""Видео урока глазами сервера: статусы файлов и дорожки субтитров по
`mediaId` нод — для `prepare_for_consumer` и гейта публикации урока."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import MediaFile
from app.services.learn_media import sign_media_path


async def subtitle_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, UUID]:
    """`{video_id: subtitle_id}` — готовая строка `kind='subtitle'` с
    `source_media_id` на видео; из нескольких берётся свежая. Монтаж
    (`variant='composed'`) своих субтитров не имеет — таймлайн у него тот же,
    что у чистовика, поэтому для него берётся дорожка ИСТОЧНИКА (один шаг
    по `source_media_id`; чистовик свою дорожку имеет всегда)."""
    if not ids:
        return {}
    out: dict[UUID, UUID] = {}
    sub_rows = await db.execute(
        select(MediaFile.id, MediaFile.source_media_id)
        .where(
            MediaFile.kind == "subtitle",
            MediaFile.status == "ready",
            MediaFile.source_media_id.in_(ids),
        )
        .order_by(MediaFile.created_at)
    )
    for sub_id, source_id in sub_rows:
        out[source_id] = sub_id
    missing = [mid for mid in ids if mid not in out]
    if not missing:
        return out
    composed_rows = await db.execute(
        select(MediaFile.id, MediaFile.source_media_id).where(
            MediaFile.id.in_(missing),
            MediaFile.variant == "composed",
            MediaFile.source_media_id.is_not(None),
        )
    )
    parents: dict[UUID, UUID] = dict(composed_rows.all())
    if not parents:
        return out
    parent_subs = await subtitle_ids(db, list(set(parents.values())))
    for mid, source_id in parents.items():
        sub = parent_subs.get(source_id)
        if sub is not None:
            out[mid] = sub
    return out


async def video_tracks(
    db: AsyncSession, media_ids: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """→ (`{media_id: url субтитров}`, `{media_id: status}`); ключи в нижнем
    регистре, как в `collect_video_ids`. Дорожки — `subtitle_ids` (у монтажа
    — дорожка чистовика)."""
    if not media_ids:
        return {}, {}
    ids = [UUID(x) for x in media_ids]
    status_rows = await db.execute(
        select(MediaFile.id, MediaFile.status).where(MediaFile.id.in_(ids))
    )
    statuses = {str(mid).lower(): status for mid, status in status_rows}
    tracks = {
        str(video_id).lower(): sign_media_path(sub_id)
        for video_id, sub_id in (await subtitle_ids(db, ids)).items()
    }
    return tracks, statuses


async def videos_not_ready(db: AsyncSession, media_ids: list[str]) -> list[str]:
    """Видео урока, которые ещё обрабатываются или не сконвертировались:
    такой урок публиковать нельзя (сотрудник получил бы плейсхолдер навсегда)."""
    _tracks, statuses = await video_tracks(db, media_ids)
    return [mid for mid, status in statuses.items() if status != "ready"]
