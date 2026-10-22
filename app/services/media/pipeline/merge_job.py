"""`merge` — склеить части (`media_parts`) в один MP4: каждая часть
приводится к целевому формату своим промежуточным файлом (или `-c copy`,
когда уже совпадает), затем `concat` demuxer без перекодирования и faststart.
Собранная строка `MediaFile` создана API в `processing` — публикуем под её
ключ и переводим в `ready`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaPart
from app.services.attachments import absolute_path
from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart
from app.services.learn_settings import get_settings_dict
from app.services.media import merge, storage
from app.services.media.autostart import maybe_enqueue_transcribe
from app.services.media.pipeline.context import JobContext, JobFailed, JobResult

KIND = "merge"


@dataclass(frozen=True)
class _Part:
    position: int
    source_media_id: UUID
    storage_key: str
    trim_start: float
    trim_end: float | None


async def _load(ctx: JobContext) -> tuple[str, list[_Part], int, int]:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        merged = await db.get(MediaFile, ctx.spec.media_id)
        if merged is None:
            raise JobFailed("media_missing", "строка собранного видео удалена")
        if merged.status != "processing":
            raise JobFailed("media_not_processing", f"статус {merged.status!r}")
        rows = (
            await db.execute(
                select(MediaPart, MediaFile)
                .join(MediaFile, MediaFile.id == MediaPart.source_media_id)
                .where(MediaPart.merged_media_id == ctx.spec.media_id)
                .order_by(MediaPart.position)
            )
        ).all()
        if len(rows) < 2:
            raise JobFailed("parts_missing", "у сборки меньше двух частей")
        parts: list[_Part] = []
        for part, source in rows:
            if source.status != "ready":
                raise JobFailed(
                    "part_not_ready", f"часть {part.position + 1}: статус {source.status!r}"
                )
            parts.append(
                _Part(
                    position=part.position,
                    source_media_id=source.id,
                    storage_key=source.storage_key,
                    trim_start=float(part.trim_start_sec or 0.0),
                    trim_end=part.trim_end_sec,
                )
            )
        defaults = (await get_settings_dict(db, ctx.spec.tenant_id)).get(
            "media_cleanup_defaults"
        ) or {}
        return (
            merged.storage_key,
            parts,
            int(defaults.get("fps_cap", 30)),
            int(defaults.get("scale_cap", 1080)),
        )


async def run(ctx: JobContext) -> JobResult:
    storage_key, parts, fps_cap, scale_cap = await _load(ctx)
    sources: list[Path] = []
    total_bytes = 0
    for part in parts:
        path = absolute_path(part.storage_key)
        if not path.is_file():
            raise JobFailed("source_missing", f"часть {part.position + 1}: файла нет в хранилище")
        total_bytes += path.stat().st_size
        sources.append(path)
    try:
        storage.ensure_free_space(ctx.settings, 2 * total_bytes)
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    ctx.set_progress("probe", 0)
    probes = [await ctx.probe(p) for p in sources]
    for part, probe in zip(parts, probes, strict=True):
        if not probe.has_video:
            raise JobFailed("no_video_stream", f"часть {part.position + 1}: нет видеодорожки")
        if part.trim_start >= probe.duration - 0.05:
            raise JobFailed(
                "bad_trim", f"часть {part.position + 1}: начало подрезки за концом записи"
            )
    try:
        target = merge.plan_target(probes, fps_cap=fps_cap, scale_cap=scale_cap)
    except ValueError as exc:
        raise JobFailed("no_video_stream", str(exc)) from None

    durations = [
        merge.part_duration(pr, trim_start=pt.trim_start, trim_end=pt.trim_end)
        for pt, pr in zip(parts, probes, strict=True)
    ]
    total = sum(durations) or 1.0
    intermediates: list[Path] = []
    report = []
    done = 0.0
    for i, (part, probe, src) in enumerate(zip(parts, probes, sources, strict=True)):
        mode = merge.part_mode(probe, target, trim_start=part.trim_start, trim_end=part.trim_end)
        dst = ctx.tmp / f"part-{i:02d}.mp4"
        await ctx.ffmpeg(
            merge.part_args(
                src,
                dst,
                probe,
                target,
                mode=mode,
                trim_start=part.trim_start,
                trim_end=part.trim_end,
                threads=ctx.settings.media_ffmpeg_threads,
            ),
            stage=f"part {i + 1}/{len(parts)}",
            duration=durations[i],
            pct_offset=done / total * 95,
            pct_scale=durations[i] / total * 0.95,
        )
        done += durations[i]
        intermediates.append(dst)
        report.append({"i": i, "mode": mode, "sec": round(durations[i], 2)})

    list_path = ctx.tmp / "concat.txt"
    list_path.write_text(merge.concat_list(intermediates), encoding="utf-8")
    out = ctx.tmp / "merged.mp4"
    await ctx.ffmpeg(
        merge.concat_args(list_path, out),
        stage="concat",
        duration=total,
        pct_offset=95,
        pct_scale=0.05,
    )
    for p in intermediates:
        p.unlink(missing_ok=True)
    if not mp4_has_faststart(out):
        raise JobFailed("faststart_missing", "ffmpeg не записал moov в начало файла")
    duration = mp4_duration_seconds(out) or total
    out_size = out.stat().st_size
    ctx.log.info(
        "media.merge_rendered",
        parts=len(parts),
        target=f"{target.width}x{target.height}@{target.fps:g}",
        output_sec=round(duration, 1),
        output_bytes=out_size,
    )

    async def apply(db: AsyncSession) -> None:
        merged = await db.get(MediaFile, ctx.spec.media_id)
        if merged is None or merged.status != "processing":
            raise JobFailed("media_not_processing", "статус изменился во время работы")
        storage.publish(out, storage_key)
        merged.size_bytes = out_size
        merged.duration_sec = duration
        merged.mime = "video/mp4"
        merged.status = "ready"
        await db.flush()
        await maybe_enqueue_transcribe(
            db, tenant_id=ctx.spec.tenant_id, media=merged, requested_by=ctx.spec.requested_by
        )

    return JobResult(
        result={
            "target": {"w": target.width, "h": target.height, "fps": target.fps},
            "parts": report,
            "output_sec": round(duration, 2),
            "output_bytes": out_size,
        },
        output_media_id=ctx.spec.media_id,
        apply=apply,
    )


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    merged = await db.get(MediaFile, ctx.spec.media_id)
    if merged is not None and merged.status == "processing":
        merged.status = "failed"
