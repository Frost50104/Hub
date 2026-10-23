"""`transcribe` — расшифровка видео урока: звук 16 кГц → замер тишины (для
нарезки) → провайдер кусками → сторож галлюцинаций и сшивка (внутри
провайдера) → `media_transcripts` + VTT как `MediaFile(kind='subtitle')` →
переиндексация уроков, где стоит это видео.

Провайдер выбирает `transcription.get_provider`: локальный STT-юнит
(`media_stt_url`, кусками ≤ 55 с с паузой между ними) или удалённый
OpenAI-совместимый. Не настроен — финальная ошибка `stt_not_configured`
(видео остаётся `ready`, здоровье показывает код)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaTranscript
from app.services import course_index
from app.services.attachments import absolute_path
from app.services.learn_settings import get_settings_dict
from app.services.media import render, silence, storage
from app.services.media.pipeline.context import JobCancelled, JobContext, JobFailed, JobResult
from app.services.media.transcription import get_provider
from app.services.media.transcription.base import plain_text, segments_to_json
from app.services.media.transcription.local_unit import TranscriptionError
from app.services.media.vtt import build_vtt

KIND = "transcribe"
# Тишина для нарезки на куски — короче порога пауз чистовика: нам нужна любая
# щель между словами, где резать безопасно.
CHUNK_SILENCE_SEC = 0.5
# WAV 16 кГц моно — 32 000 байт/с.
WAV_BYTES_PER_SEC = 32_000


async def _load(ctx: JobContext) -> tuple[str, str, float | None, str]:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена")
        if media.kind != "video":
            raise JobFailed("not_video", f"kind={media.kind!r}")
        if media.status != "ready":
            raise JobFailed("media_not_ready", f"статус {media.status!r}")
        settings = await get_settings_dict(db, ctx.spec.tenant_id)
        return (
            media.storage_key,
            media.file_name,
            media.duration_sec,
            str(settings.get("media_glossary") or ""),
        )


async def run(ctx: JobContext) -> JobResult:
    provider = get_provider(ctx.settings)
    if provider is None:
        raise JobFailed("stt_not_configured", "расшифровка не настроена (MEDIA_STT_URL)")
    storage_key, file_name, known_duration, glossary = await _load(ctx)
    src = absolute_path(storage_key)
    if not src.is_file():
        raise JobFailed("source_missing", "файл видео отсутствует в хранилище")

    ctx.set_progress("probe", 0)
    probe = await ctx.probe(src)
    if not probe.has_audio:
        raise JobFailed("no_audio_stream", "в видео нет звуковой дорожки")
    duration = float(known_duration or probe.duration or 0.0)
    if duration <= 0:
        raise JobFailed("no_duration", "не удалось определить длительность")
    try:
        storage.ensure_free_space(ctx.settings, int(duration * WAV_BYTES_PER_SEC) + 2**20)
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    wav = ctx.tmp / "audio16k.wav"
    await ctx.ffmpeg(
        render.audio16k_args(src, wav), stage="audio", duration=duration, pct_scale=0.05
    )
    nf_log = await ctx.ffmpeg(
        render.noise_floor_args(wav),
        stage="silence",
        duration=duration,
        pct_offset=5,
        pct_scale=0.02,
        capture_stderr=True,
        loglevel="info",
    )
    threshold = silence.threshold_db(silence.parse_noise_floor(nf_log))
    sd_log = await ctx.ffmpeg(
        render.silencedetect_args(wav, threshold_db=threshold, min_pause=CHUNK_SILENCE_SEC),
        stage="silence",
        duration=duration,
        pct_offset=7,
        pct_scale=0.03,
        capture_stderr=True,
        loglevel="info",
    )
    silences = silence.parse_silencedetect(sd_log, duration=duration)

    chunks_done = {"n": 0, "total": 0}

    async def on_chunk(done: int, total: int) -> None:
        chunks_done["n"], chunks_done["total"] = done, total
        ctx.set_progress("transcribe", int(10 + 88 * done / max(1, total)))

    ctx.set_progress("transcribe", 10)
    try:
        result = await provider.transcribe_file(
            wav,
            language=ctx.settings.stt_language,
            glossary=glossary,
            beam_size=ctx.settings.media_stt_beam_size,
            duration=duration,
            silences=silences,
            on_chunk=on_chunk,
            cancel=ctx.cancel,
        )
    except TranscriptionError as exc:
        if exc.code == "cancelled":
            raise JobCancelled() from None
        raise JobFailed(exc.code, exc.message, final=exc.final) from exc
    segments = segments_to_json(result.segments)
    text = plain_text(result.segments)
    vtt_text = build_vtt(segments)
    vtt_path = ctx.tmp / "subtitles.vtt"
    vtt_path.write_text(vtt_text, encoding="utf-8")
    vtt_size = vtt_path.stat().st_size
    stem = storage.stem_of_storage_key(storage_key, ctx.spec.media_id)
    display_name = f"{Path(file_name).stem or 'video'}.vtt"
    ctx.log.info(
        "media.transcribed",
        provider=result.provider,
        model=result.model,
        segments=len(segments),
        chars=len(text),
        chunks=chunks_done["total"],
        duration_sec=round(duration, 1),
    )

    job_result = JobResult(
        result={
            "provider": result.provider,
            "model": result.model,
            "language": result.language,
            "segments": len(segments),
            "chars": len(text),
            "chunks": chunks_done["total"],
            "duration_sec": round(duration, 1),
            "threshold_db": threshold,
        }
    )

    async def apply(db: AsyncSession) -> None:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена во время работы")
        stmt = pg_insert(MediaTranscript).values(
            media_id=media.id,
            tenant_id=ctx.spec.tenant_id,
            provider=result.provider,
            model=result.model[:64],
            language=result.language[:8],
            text=text,
            segments=segments,
            duration_sec=duration,
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[MediaTranscript.media_id],
                set_={
                    "provider": stmt.excluded.provider,
                    "model": stmt.excluded.model,
                    "language": stmt.excluded.language,
                    "text": stmt.excluded.text,
                    "segments": stmt.excluded.segments,
                    "duration_sec": stmt.excluded.duration_sec,
                    "source_transcript_media_id": None,
                },
            )
        )
        existing = (
            await db.execute(
                select(MediaFile)
                .where(MediaFile.kind == "subtitle", MediaFile.source_media_id == media.id)
                .order_by(MediaFile.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Субтитры — регенерируемы: повторная расшифровка переписывает файл
            # под тем же ключом, ссылка `<track>` остаётся прежней.
            storage.publish(vtt_path, existing.storage_key)
            existing.size_bytes = vtt_size
            existing.status = "ready"
            existing.file_name = display_name
            subtitle_id: UUID = existing.id
        else:
            sub = MediaFile(
                tenant_id=ctx.spec.tenant_id,
                kind="subtitle",
                role="content",
                status="ready",
                storage_key="",
                file_name=display_name,
                mime="text/vtt",
                size_bytes=vtt_size,
                source_media_id=media.id,
                uploaded_by=None,
            )
            db.add(sub)
            await db.flush()
            key = storage.derived_storage_key(ctx.spec.tenant_id, sub.id, f"{stem}.vtt")
            storage.publish(vtt_path, key)
            sub.storage_key = key
            subtitle_id = sub.id
        job_result.output_media_id = subtitle_id
        await db.flush()
        indexed = await course_index.reindex_lessons_for_media(db, media.id)
        job_result.result["lessons_indexed"] = indexed

    job_result.apply = apply
    return job_result


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    """Видео остаётся `ready`: расшифровка — надстройка, её отсутствие не
    ломает урок; повтор — кнопкой."""
