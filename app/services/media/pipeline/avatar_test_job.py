"""`avatar_test` — «Проверить на 10 секундах»: сцена-референс + встроенный
русский образец (`ops/stt/smoke-ru.webm`, 4,6 с, зациклен до 10 с — Hedra
тарифицирует длину ЗВУКА, и 10 секунд обязаны быть честными) → один запрос Hedra → клип
сохраняется как `MediaFile(kind='video', role='scene', variant='composed',
source_media_id=сцена)` и показывается в карточке «Гусь» админки. Это же —
первый живой прогон на staging (модерация мультяшного гуся, качество)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.services.attachments import absolute_path
from app.services.learn_settings import get_settings_dict
from app.services.media import storage
from app.services.media.hedra.client import HedraClient, HedraError
from app.services.media.pipeline.compose_job import GOOSE_PROMPT
from app.services.media.pipeline.context import JobCancelled, JobContext, JobFailed, JobResult

KIND = "avatar_test"
# parents: pipeline → media → services → app → корень репозитория.
SAMPLE = Path(__file__).resolve().parents[4] / "ops" / "stt" / "smoke-ru.webm"
SAMPLE_SEC = 10.0


async def run(ctx: JobContext) -> JobResult:
    s = ctx.settings
    if not s.media_avatar_enabled or not s.hedra_api_key:
        raise JobFailed(
            "avatar_disabled", "гусь выключен на сервере (MEDIA_AVATAR_ENABLED / HEDRA_API_KEY)"
        )
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        scene = await db.get(MediaFile, ctx.spec.media_id)
        if scene is None or scene.kind != "image" or scene.status != "ready":
            raise JobFailed("scene_missing", "сцена гуся не задана или не готова")
        settings = await get_settings_dict(db, ctx.spec.tenant_id)
        resolution = str(
            (ctx.spec.params or {}).get("resolution")
            or settings.get("media_avatar_resolution", "720p")
        )
        scene_key, scene_mime = scene.storage_key, scene.mime
    scene_path = absolute_path(scene_key)
    if not scene_path.is_file():
        raise JobFailed("scene_missing", "файла сцены нет в хранилище")
    if not SAMPLE.is_file():
        raise JobFailed("sample_missing", f"нет образца {SAMPLE}")
    voice = ctx.tmp / "sample.mp3"
    await ctx.ffmpeg(
        [
            "-stream_loop",
            "-1",
            "-i",
            str(SAMPLE),
            "-t",
            f"{SAMPLE_SEC:.1f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(voice),
        ],
        stage="voice",
        duration=SAMPLE_SEC,
        pct_scale=0.05,
    )
    client = HedraClient(
        api_key=s.hedra_api_key, base_url=s.hedra_base_url, timeout_sec=s.hedra_timeout_sec
    )
    state: dict[str, Any] = dict((ctx.spec.params or {}).get("hedra_state") or {})
    clip = ctx.tmp / "goose-test.mp4"
    try:
        if not state.get("job_id"):
            image_ref = await client.upload_file(
                scene_path, purpose="image", mime=scene_mime or "image/png"
            )
            audio_ref = await client.upload_file(voice, purpose="audio", mime="audio/mpeg")
            state["job_id"] = await client.submit(
                image_ref=image_ref,
                audio_ref=audio_ref,
                resolution=resolution,
                duration_ms=int(SAMPLE_SEC * 1000),
                idempotency_key=f"{ctx.spec.id}:test",
                prompt=GOOSE_PROMPT,
            )
            ctx.set_progress("goose", 10)
            ctx.progress["hedra"] = state
            await ctx.persist_now()
            ctx.log.info("media.hedra_submitted", chunk="test", job_id=state["job_id"])
        ctx.set_progress("goose", 10)
        ctx.progress["hedra"] = state

        async def on_tick(job: Any) -> None:
            state["status"] = job.status
            ctx.set_progress("goose", 10 + int(80 * (job.progress or 0)))
            ctx.progress["hedra"] = state

        done = await client.wait(
            state["job_id"],
            poll_sec=s.hedra_poll_sec,
            max_wait_sec=s.hedra_job_max_wait_sec,
            on_tick=on_tick,
            cancel=ctx.cancel,
        )
        if not done.output_url:
            raise JobFailed("hedra_no_output", "Hedra не отдала ссылку на результат", final=False)
        await client.download(done.output_url, clip)
        state["cost"] = done.cost
    except HedraError as exc:
        if exc.code == "cancelled":
            raise JobCancelled() from None
        raise JobFailed(exc.code, exc.message, final=exc.final) from exc
    out_size = clip.stat().st_size
    job_result = JobResult(
        result={
            "hedra": state,
            "billed_seconds": int(SAMPLE_SEC),
            "resolution": resolution,
            "output_bytes": out_size,
        }
    )

    async def apply(db: AsyncSession) -> None:
        row = MediaFile(
            tenant_id=ctx.spec.tenant_id,
            kind="video",
            role="scene",
            status="ready",
            storage_key="",
            file_name="Проверка гуся — 10 с.mp4",
            mime="video/mp4",
            size_bytes=out_size,
            duration_sec=SAMPLE_SEC,
            source_media_id=ctx.spec.media_id,
            variant="composed",
            uploaded_by=ctx.spec.requested_by,
        )
        db.add(row)
        await db.flush()
        key = storage.derived_storage_key(ctx.spec.tenant_id, row.id, "goose-test.mp4")
        storage.publish(clip, key)
        row.storage_key = key
        job_result.output_media_id = row.id

    job_result.apply = apply
    return job_result


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    """Сцена остаётся; минуты вернёт `billed_seconds=0` финала."""
