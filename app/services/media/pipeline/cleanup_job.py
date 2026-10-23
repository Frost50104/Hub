"""`cleanup` — чистовик: ужатые паузы (решение владельца — не вырезать, а
укоротить до ~0,7 с), шумодав, выровненная громкость, потолки fps/высоты.
Результат — НОВАЯ строка `MediaFile(variant='cleaned', source_media_id=…)`,
её транскрипт с перемапленными таймкодами и VTT; следом автоматически
ставится `analyze` (раскадровка для монтажа). Оригинал не меняется.

Паузы ищутся пересечением тишины по звуку и зазоров транскрипта — тихая
речь не режется; без транскрипта (STT не настроен) — только по тишине.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaTranscript
from app.services.attachments import absolute_path
from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart
from app.services.learn_settings import get_settings_dict
from app.services.media import edl, jobs, render, silence, storage
from app.services.media.cleanup_plan import CleanupParams, plan_cleanup
from app.services.media.pipeline.context import JobContext, JobFailed, JobResult
from app.services.media.transcription.base import plain_text_of_json
from app.services.media.vtt import build_vtt

KIND = "cleanup"
WAV_BYTES_PER_SEC = 32_000


async def _load(ctx: JobContext) -> tuple[MediaFile, MediaTranscript | None, dict[str, Any]]:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена")
        if media.kind != "video":
            raise JobFailed("not_video", f"kind={media.kind!r}")
        if media.status != "ready":
            raise JobFailed("media_not_ready", f"статус {media.status!r}")
        transcript = await db.get(MediaTranscript, media.id)
        settings = await get_settings_dict(db, ctx.spec.tenant_id)
        defaults = dict(settings.get("media_cleanup_defaults") or {})
        return media, transcript, defaults


async def run(ctx: JobContext) -> JobResult:
    media, transcript, defaults = await _load(ctx)
    params = CleanupParams.from_settings(defaults, ctx.spec.params)
    src = absolute_path(media.storage_key)
    if not src.is_file():
        raise JobFailed("source_missing", "файл видео отсутствует в хранилище")
    size = src.stat().st_size
    ctx.set_progress("probe", 0)
    probe = await ctx.probe(src)
    if not probe.has_video:
        raise JobFailed("no_video_stream", "в файле нет видеодорожки")
    if not probe.has_audio:
        raise JobFailed(
            "no_audio_stream", "в видео нет звуковой дорожки — чистовику нечего чистить"
        )
    duration = float(media.duration_sec or probe.duration or 0.0)
    if duration <= 0:
        raise JobFailed("no_duration", "не удалось определить длительность")
    try:
        storage.ensure_free_space(ctx.settings, 2 * size + int(duration * WAV_BYTES_PER_SEC))
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    # 1. Звук 16 кГц → шумовой пол → тишина.
    wav = ctx.tmp / "audio16k.wav"
    await ctx.ffmpeg(
        render.audio16k_args(src, wav), stage="audio", duration=duration, pct_scale=0.04
    )
    noise_floor: float | None = None
    threshold = silence.threshold_db(None)
    silences: list[edl.Interval] = []
    if params.pauses_enabled:
        nf_log = await ctx.ffmpeg(
            render.noise_floor_args(wav),
            stage="silence",
            duration=duration,
            pct_offset=4,
            pct_scale=0.02,
            capture_stderr=True,
            loglevel="info",
        )
        noise_floor = silence.parse_noise_floor(nf_log)
        threshold = silence.threshold_db(noise_floor)
        sd_log = await ctx.ffmpeg(
            render.silencedetect_args(
                wav, threshold_db=threshold, min_pause=max(0.3, params.min_pause_sec)
            ),
            stage="silence",
            duration=duration,
            pct_offset=6,
            pct_scale=0.02,
            capture_stderr=True,
            loglevel="info",
        )
        silences = silence.parse_silencedetect(sd_log, duration=duration)

    # 2. План вырезки.
    segments = list(transcript.segments or []) if transcript is not None else None
    plan = plan_cleanup(params, duration=duration, silences=silences, segments=segments)
    ctx.log.info(
        "media.cleanup_planned",
        pauses=len(plan.pauses),
        removed_sec=round(plan.removed_sec, 1),
        threshold_db=threshold,
    )

    # 3. Громкость: первый проход по УЖЕ вырезанному и очищенному треку.
    denoise = render.denoise_filter(params.denoise)
    measured: dict[str, float] | None = None
    if params.loudnorm:
        log = await ctx.ffmpeg(
            render.loudnorm_pass1_args(
                src,
                plan.kept,
                denoise=denoise,
                i=params.loudnorm_i,
                tp=params.loudnorm_tp,
                lra=params.loudnorm_lra,
            ),
            stage="loudness",
            duration=duration,
            pct_offset=8,
            pct_scale=0.12,
            capture_stderr=True,
            loglevel="info",
        )
        try:
            measured = silence.parse_loudnorm_json(log)
        except ValueError as exc:
            raise JobFailed("loudnorm_measure", str(exc)) from None

    # 4. Рендер одним проходом.
    fps = min(probe.fps or params.fps_cap, params.fps_cap)
    script = ctx.tmp / "filters.txt"
    script.write_text(
        render.filter_script(
            plan.kept,
            denoise=denoise,
            i=params.loudnorm_i,
            tp=params.loudnorm_tp,
            lra=params.loudnorm_lra,
            measured=measured,
            fps=fps,
            scale_cap=params.scale_cap,
        ),
        encoding="utf-8",
    )
    out = ctx.tmp / "cleaned.mp4"
    await ctx.ffmpeg(
        render.render_args(src, out, script, threads=ctx.settings.media_ffmpeg_threads),
        stage="render",
        duration=plan.output_sec,
        pct_offset=20,
        pct_scale=0.78,
    )
    if not mp4_has_faststart(out):
        raise JobFailed("faststart_missing", "ffmpeg не записал moov в начало файла")
    out_duration = mp4_duration_seconds(out) or plan.output_sec
    out_size = out.stat().st_size

    # 5. Транскрипт и субтитры чистовика — перемаппинг, не новая расшифровка.
    remapped: list[dict[str, Any]] | None = None
    vtt_path: Path | None = None
    if segments:
        remapped = edl.remap_segments(segments, plan.removed)
        vtt_path = ctx.tmp / "cleaned.vtt"
        vtt_path.write_text(build_vtt(remapped), encoding="utf-8")

    stem = storage.stem_of_storage_key(media.storage_key, media.id)
    display_stem = Path(media.file_name).stem or "video"
    ctx.log.info(
        "media.cleanup_rendered",
        source_sec=round(duration, 1),
        output_sec=round(out_duration, 1),
        output_bytes=out_size,
        loudnorm=measured is not None,
    )
    job_result = JobResult(
        result={
            "params": params.to_json(),
            "noise_floor_db": noise_floor,
            "threshold_db": threshold,
            "pauses": plan.report,
            "stats": {**plan.stats(), "output_sec": round(out_duration, 2)},
            "loudnorm": measured,
            "transcript": remapped is not None,
        }
    )

    async def apply(db: AsyncSession) -> None:
        source = await db.get(MediaFile, media.id)
        if source is None:
            raise JobFailed("media_missing", "строка медиа удалена во время работы")
        cleaned = MediaFile(
            tenant_id=ctx.spec.tenant_id,
            kind="video",
            role="content",
            status="ready",
            storage_key="",
            file_name=f"{display_stem} — чистовик.mp4"[:255],
            mime="video/mp4",
            size_bytes=out_size,
            duration_sec=out_duration,
            source_media_id=source.id,
            variant="cleaned",
            uploaded_by=ctx.spec.requested_by,
        )
        db.add(cleaned)
        await db.flush()
        key = storage.derived_storage_key(ctx.spec.tenant_id, cleaned.id, f"{stem}-cleaned.mp4")
        storage.publish(out, key)
        cleaned.storage_key = key
        if remapped is not None and transcript is not None and vtt_path is not None:
            db.add(
                MediaTranscript(
                    media_id=cleaned.id,
                    tenant_id=ctx.spec.tenant_id,
                    provider=transcript.provider,
                    model=transcript.model,
                    language=transcript.language,
                    text=plain_text_of_json(remapped),
                    segments=remapped,
                    duration_sec=out_duration,
                    source_transcript_media_id=source.id,
                )
            )
            sub = MediaFile(
                tenant_id=ctx.spec.tenant_id,
                kind="subtitle",
                role="content",
                status="ready",
                storage_key="",
                file_name=f"{display_stem} — чистовик.vtt"[:255],
                mime="text/vtt",
                size_bytes=vtt_path.stat().st_size,
                source_media_id=cleaned.id,
            )
            db.add(sub)
            await db.flush()
            sub_key = storage.derived_storage_key(ctx.spec.tenant_id, sub.id, f"{stem}-cleaned.vtt")
            storage.publish(vtt_path, sub_key)
            sub.storage_key = sub_key
        await db.flush()
        # Раскадровка чистовика — дёшево и сразу: шторка «Монтаж» откроется
        # с готовыми отрезками.
        try:
            await jobs.enqueue(
                db,
                tenant_id=ctx.spec.tenant_id,
                media_id=cleaned.id,
                kind="analyze",
                requested_by=ctx.spec.requested_by,
            )
        except jobs.JobConflict:
            pass
        job_result.output_media_id = cleaned.id

    job_result.apply = apply
    return job_result


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    """Оригинал не трогаем — чистовик просто не появился."""
