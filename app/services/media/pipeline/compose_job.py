"""`compose` — монтаж: отрезки спикера чистовика заменяются клипами гуся из
Hedra, вставки идут поверх голоса, звук — целиком из чистовика. Задание
ВОЗОБНОВЛЯЕМО: состояние по кускам живёт в `result.hedra.chunks`
(`idempotency_key`, `job_id`, `status`, `cost`), после рестарта воркера
куски с `job_id` не отправляются заново — только дожидаются и скачиваются.

Деньги: отправляется только то, что в `params.chunks` (снимок раскадровки
на момент заказа); `result.billed_seconds` — по факту отправленных кусков,
модерация/ошибка до отправки оставляет 0 (резерв возвращается).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaStoryboard, MediaTranscript
from app.services.attachments import absolute_path
from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart
from app.services.learn_settings import get_settings_dict
from app.services.media import compose_plan, storage
from app.services.media.hedra.client import HedraClient, HedraError
from app.services.media.hedra.pricing import billed_seconds
from app.services.media.pipeline.context import JobCancelled, JobContext, JobFailed, JobResult
from app.services.media.transcription.base import transcript_gaps

KIND = "compose"
GOOSE_PROMPT = (
    "Friendly cartoon goose character talking to the camera, natural speech, "
    "subtle head movements, keep the background still"
)


def _client(ctx: JobContext) -> HedraClient:
    s = ctx.settings
    if not s.media_avatar_enabled or not s.hedra_api_key:
        raise JobFailed(
            "avatar_disabled", "гусь выключен на сервере (MEDIA_AVATAR_ENABLED / HEDRA_API_KEY)"
        )
    return HedraClient(
        api_key=s.hedra_api_key, base_url=s.hedra_base_url, timeout_sec=s.hedra_timeout_sec
    )


async def _load(ctx: JobContext) -> dict[str, Any]:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена")
        if media.kind != "video" or media.status != "ready":
            raise JobFailed("media_not_ready", f"kind={media.kind!r} status={media.status!r}")
        board = await db.get(MediaStoryboard, media.id)
        transcript = await db.get(MediaTranscript, media.id)
        settings = await get_settings_dict(db, ctx.spec.tenant_id)
        scene_id = settings.get("media_scene_media_id")
        scene = await db.get(MediaFile, UUID(str(scene_id))) if scene_id else None
        insert_ids = [UUID(str(i["media_id"])) for i in (board.inserts if board else [])]
        inserts: dict[UUID, MediaFile] = {}
        for iid in insert_ids:
            row = await db.get(MediaFile, iid)
            if row is not None:
                inserts[iid] = row
        return {
            "storage_key": media.storage_key,
            "file_name": media.file_name,
            "duration": float(media.duration_sec or 0.0),
            "segments": list(board.segments or []) if board else [],
            "inserts": list(board.inserts or []) if board else [],
            "goose_enabled": bool(board.goose_enabled) if board else False,
            "gaps": transcript_gaps(transcript.segments, float(media.duration_sec or 0.0))
            if transcript and media.duration_sec
            else [],
            "scene_key": scene.storage_key if scene and scene.status == "ready" else None,
            "scene_mime": scene.mime if scene else None,
            "insert_keys": {
                str(k): v.storage_key for k, v in inserts.items() if v.status == "ready"
            },
            "resolution": str(settings.get("media_avatar_resolution", "720p")),
        }


async def _hedra_chunks(
    ctx: JobContext,
    client: HedraClient,
    *,
    src: Path,
    chunks: list[tuple[float, float]],
    scene_path: Path,
    scene_mime: str,
    resolution: str,
    state: dict[str, Any],
) -> list[Path]:
    """Куски гуся: загрузить сцену и голос → submit → записать `job_id` СРАЗУ
    (`ctx.persist_now`) → дождаться → скачать. Состояние — в `state["chunks"]`.
    Handle файла Hedra живёт ~1 ч, а кусок ждёт результата до 30 мин — поэтому
    сцена грузится перед КАЖДЫМ submit, а не один раз на задание."""
    s = ctx.settings
    rows: list[dict[str, Any]] = state.setdefault("chunks", [])
    while len(rows) < len(chunks):
        i = len(rows)
        rows.append(
            {
                "i": i,
                "segment": [round(chunks[i][0], 3), round(chunks[i][1], 3)],
                "idempotency_key": f"{ctx.spec.id}:{i}",
                "job_id": None,
                "status": "pending",
                "duration_ms": int(round((chunks[i][1] - chunks[i][0]) * 1000)),
                "cost": None,
            }
        )
    clips: list[Path] = []
    for i, (cs, ce) in enumerate(chunks):
        if ctx.cancel.is_set():
            raise JobCancelled()
        row = rows[i]
        ctx.set_progress(f"goose {i + 1}/{len(chunks)}", int(20 + 60 * i / max(1, len(chunks))))
        ctx.progress["hedra"] = {"chunks": rows}
        clip = ctx.tmp / f"goose-{i:02d}.mp4"
        try:
            if not row.get("job_id"):
                voice = ctx.tmp / f"voice-{i:02d}.mp3"
                await ctx.ffmpeg(
                    compose_plan.voice_slice_args(src, voice, cs, ce),
                    stage=f"voice {i + 1}/{len(chunks)}",
                    duration=ce - cs,
                    pct_offset=20 + 60 * i / max(1, len(chunks)),
                    pct_scale=0.01,
                )
                image_ref = await client.upload_file(scene_path, purpose="image", mime=scene_mime)
                audio_ref = await client.upload_file(voice, purpose="audio", mime="audio/mpeg")
                row["job_id"] = await client.submit(
                    image_ref=image_ref,
                    audio_ref=audio_ref,
                    resolution=resolution,
                    duration_ms=row["duration_ms"],
                    idempotency_key=row["idempotency_key"],
                    prompt=GOOSE_PROMPT,
                )
                row["status"] = "submitted"
                ctx.progress["hedra"] = {"chunks": rows}
                await ctx.persist_now()
                ctx.log.info("media.hedra_submitted", chunk=i, job_id=row["job_id"])
            # Нарезка голоса переписала стадию на «voice i/n» — вернуть «goose».
            ctx.set_progress(f"goose {i + 1}/{len(chunks)}", int(20 + 60 * i / max(1, len(chunks))))
            ctx.progress["hedra"] = {"chunks": rows}

            async def on_tick(job: Any, row: dict[str, Any] = row, i: int = i) -> None:
                row["status"] = job.status
                if job.progress is not None:
                    row["progress"] = job.progress
                    # Ход Hedra по куску — в общий процент (20..80 — доля гуся).
                    ctx.set_progress(
                        f"goose {i + 1}/{len(chunks)}",
                        int(20 + 60 * (i + max(0.0, min(1.0, job.progress))) / max(1, len(chunks))),
                    )
                    ctx.progress["hedra"] = {"chunks": rows}

            done = await client.wait(
                row["job_id"],
                poll_sec=s.hedra_poll_sec,
                max_wait_sec=s.hedra_job_max_wait_sec,
                on_tick=on_tick,
                cancel=ctx.cancel,
            )
            if not done.output_url:
                raise JobFailed(
                    "hedra_no_output", "Hedra не отдала ссылку на результат", final=False
                )
            await client.download(done.output_url, clip)
            row["status"] = "downloaded"
            row["cost"] = done.cost
            clips.append(clip)
        except HedraError as exc:
            if exc.code == "cancelled":
                raise JobCancelled() from None
            row["status"] = "error"
            row["error"] = exc.code
            raise JobFailed(exc.code, exc.message, final=exc.final) from exc
    return clips


async def run(ctx: JobContext) -> JobResult:
    info = await _load(ctx)
    duration = info["duration"]
    if duration <= 0:
        raise JobFailed("no_duration", "не удалось определить длительность")
    src = absolute_path(info["storage_key"])
    if not src.is_file():
        raise JobFailed("source_missing", "файл чистовика отсутствует в хранилище")
    params = ctx.spec.params or {}
    resolution = str(params.get("resolution") or info["resolution"])
    goose_enabled = bool(params.get("goose_enabled", info["goose_enabled"]))
    plan = compose_plan.plan_compose(
        duration=duration,
        segments=info["segments"],
        inserts=info["inserts"],
        goose_enabled=goose_enabled,
        resolution=resolution,
        transcript_gaps=info["gaps"],
    )
    if not plan.chunks and not plan.inserts:
        raise JobFailed("nothing_to_compose", "ни отрезков гуся, ни вставок")
    insert_files: list[Path] = []
    for ins in plan.inserts:
        key = info["insert_keys"].get(str(ins["media_id"]))
        if not key:
            raise JobFailed("insert_missing", f"вставка {ins['media_id']} не готова или удалена")
        path = absolute_path(key)
        if not path.is_file():
            raise JobFailed("insert_missing", f"файла вставки нет в хранилище: {ins['media_id']}")
        insert_files.append(path)
    size = src.stat().st_size
    try:
        storage.ensure_free_space(ctx.settings, 3 * size)
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    ctx.set_progress("probe", 0)
    probe = await ctx.probe(src)
    width, height = probe.display_size or (1280, 720)
    fps = min(probe.fps or 30.0, 30.0)

    state: dict[str, Any] = dict((ctx.spec.params or {}).get("hedra_state") or {})
    clips: list[Path] = []
    if plan.chunks:
        if not info["scene_key"]:
            raise JobFailed("scene_missing", "сцена гуся не задана в настройках")
        client = _client(ctx)
        clips = await _hedra_chunks(
            ctx,
            client,
            src=src,
            chunks=plan.chunks,
            scene_path=absolute_path(info["scene_key"]),
            scene_mime=info["scene_mime"] or "image/png",
            resolution=resolution,
            state=state,
        )
    pieces = compose_plan.timeline_pieces(
        duration,
        plan.chunks,
        plan.inserts,
        first_chunk_input=1,
        first_insert_input=1 + len(clips),
    )
    script = ctx.tmp / "compose.txt"
    script.write_text(
        compose_plan.filter_script(pieces, width=width, height=height, fps=fps), encoding="utf-8"
    )
    out = ctx.tmp / "composed.mp4"
    await ctx.ffmpeg(
        compose_plan.render_args(
            src, clips, insert_files, script, out, threads=ctx.settings.media_ffmpeg_threads
        ),
        stage="render",
        duration=duration,
        pct_offset=80,
        pct_scale=0.19,
    )
    if not mp4_has_faststart(out):
        raise JobFailed("faststart_missing", "ffmpeg не записал moov в начало файла")
    out_duration = mp4_duration_seconds(out) or duration
    out_size = out.stat().st_size
    billed = billed_seconds(plan.chunks) if clips else 0
    stem = storage.stem_of_storage_key(info["storage_key"], ctx.spec.media_id)
    display_stem = Path(info["file_name"]).stem.replace(" — чистовик", "") or "video"
    job_result = JobResult(
        result={
            "plan": plan.summary(),
            "hedra": {**state, "chunks": state.get("chunks", [])},
            "billed_seconds": billed,
            "cost_cents": plan.cost_cents if clips else 0,
            "output_sec": round(out_duration, 2),
            "output_bytes": out_size,
        }
    )

    async def apply(db: AsyncSession) -> None:
        source = await db.get(MediaFile, ctx.spec.media_id)
        if source is None:
            raise JobFailed("media_missing", "строка медиа удалена во время работы")
        composed = MediaFile(
            tenant_id=ctx.spec.tenant_id,
            kind="video",
            role="content",
            status="ready",
            storage_key="",
            file_name=f"{display_stem} — монтаж.mp4"[:255],
            mime="video/mp4",
            size_bytes=out_size,
            duration_sec=out_duration,
            source_media_id=source.id,
            variant="composed",
            uploaded_by=ctx.spec.requested_by,
        )
        db.add(composed)
        await db.flush()
        key = storage.derived_storage_key(ctx.spec.tenant_id, composed.id, f"{stem}-composed.mp4")
        storage.publish(out, key)
        composed.storage_key = key
        job_result.output_media_id = composed.id

    job_result.apply = apply
    return job_result


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    """Чистовик остаётся; `billed_seconds` в result финала ставит воркер = 0,
    если куски не отправлялись (резерв возвращается)."""
