"""`normalize` — привести загрузку (MOV/WebM/MP4 без faststart) к MP4
H.264/AAC с faststart НА МЕСТЕ, пока строка в `processing` и файл никто не
видел. Ремукс, когда можно (секунды), иначе перекодирование с потолками
fps/высоты из `media_cleanup_defaults` тенанта.

Исходник удаляется только ПОСЛЕ коммита: упади транзакция после `os.replace`,
повтор задания нашёл бы и источник, и уже готовый файл.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.services.attachments import absolute_path
from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart
from app.services.learn_settings import get_settings_dict
from app.services.media import normalize, storage
from app.services.media.autostart import maybe_enqueue_transcribe
from app.services.media.pipeline.context import JobContext, JobFailed, JobResult

KIND = "normalize"


def _mp4_display_name(file_name: str) -> str:
    stem = Path(file_name).stem or "video"
    return f"{stem}.mp4"


async def _load(ctx: JobContext) -> tuple[str, str, int, int]:
    """(storage_key, file_name, fps_cap, scale_cap) короткой транзакцией."""
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена")
        if media.status != "processing":
            raise JobFailed("media_not_processing", f"статус {media.status!r}")
        defaults = (await get_settings_dict(db, ctx.spec.tenant_id)).get(
            "media_cleanup_defaults"
        ) or {}
        return (
            media.storage_key,
            media.file_name,
            int(defaults.get("fps_cap", 30)),
            int(defaults.get("scale_cap", 1080)),
        )


async def run(ctx: JobContext) -> JobResult:
    storage_key, file_name, fps_cap, scale_cap = await _load(ctx)
    src = absolute_path(storage_key)
    if not src.is_file():
        raise JobFailed("source_missing", "исходный файл отсутствует в хранилище")
    size = src.stat().st_size
    try:
        storage.ensure_free_space(ctx.settings, 2 * size)
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    ctx.set_progress("probe", 0)
    probe = await ctx.probe(src)
    if not probe.has_video:
        raise JobFailed("no_video_stream", "в файле нет видеодорожки")
    mode = normalize.plan(probe, fps_cap=fps_cap, scale_cap=scale_cap)
    out = ctx.tmp / "normalized.mp4"
    await ctx.ffmpeg(
        normalize.args(
            mode,
            src,
            out,
            probe,
            fps_cap=fps_cap,
            scale_cap=scale_cap,
            threads=ctx.settings.media_ffmpeg_threads,
        ),
        stage="remux" if mode == "copy" else "transcode",
        duration=probe.duration,
    )
    if not mp4_has_faststart(out):
        raise JobFailed("faststart_missing", "ffmpeg не записал moov в начало файла")
    duration = mp4_duration_seconds(out) or probe.duration or None
    out_size = out.stat().st_size

    stem = storage.stem_of_storage_key(storage_key, ctx.spec.media_id)
    new_key = storage.derived_storage_key(ctx.spec.tenant_id, ctx.spec.media_id, f"{stem}.mp4")
    ctx.log.info(
        "media.normalize_rendered",
        mode=mode,
        source_sec=round(probe.duration, 1),
        output_sec=round(duration or 0, 1),
        source_bytes=size,
        output_bytes=out_size,
    )

    async def apply(db: AsyncSession) -> None:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None or media.status != "processing":
            raise JobFailed("media_not_processing", "статус изменился во время работы")
        storage.publish(out, new_key)
        media.storage_key = new_key
        media.mime = "video/mp4"
        media.size_bytes = out_size
        media.duration_sec = duration
        media.file_name = _mp4_display_name(file_name)
        media.status = "ready"
        await db.flush()
        # Готовое видео урока сразу уходит на расшифровку (если настроено).
        await maybe_enqueue_transcribe(
            db, tenant_id=ctx.spec.tenant_id, media=media, requested_by=ctx.spec.requested_by
        )

    cleanup = [src] if absolute_path(new_key) != src else []
    return JobResult(
        result={
            "mode": mode,
            "source": {
                "container": probe.container,
                "vcodec": probe.vcodec,
                "acodec": probe.acodec,
                "size": list(probe.display_size or ()),
                "fps": probe.fps,
                "bytes": size,
            },
            "output_sec": duration,
            "output_bytes": out_size,
        },
        output_media_id=ctx.spec.media_id,
        apply=apply,
        cleanup_after_commit=cleanup,
    )


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    media = await db.get(MediaFile, ctx.spec.media_id)
    if media is not None and media.status == "processing":
        media.status = "failed"
