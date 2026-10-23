"""`analyze` — раскадровка видео для монтажа: где в кадре человек (→ гусь во
весь кадр), где показ экрана (→ только голос). Кадр в секунду → Haar-каскады
OpenCV (обнаружение ЛЮБОГО лица, не распознавание) → доля кадра под самым
большим лицом → чистая математика `storyboard.py` (порог, сглаживание,
склейка, притяжка к сменам кадра). Ставится автоматически после `cleanup` и
по кнопке. Правленная автором раскадровка (`edited_by`) не перезаписывается —
обновляются `face_track` и `segments_auto`.

OpenCV импортируется только здесь, в воркере; в API-процессе его нет
(сторож `tests/unit/test_media_faces.py`).
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaStoryboard
from app.services.attachments import absolute_path
from app.services.learn_settings import get_settings_dict
from app.services.media import faces, storage, storyboard
from app.services.media.pipeline.context import JobContext, JobFailed, JobResult

KIND = "analyze"
# Кадр 320 px × ~15 КБ: час видео — ~55 МБ временных файлов.
FRAME_BYTES_PER_SEC = 20_000


async def _load(ctx: JobContext) -> tuple[MediaFile, dict[str, Any]]:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        media = await db.get(MediaFile, ctx.spec.media_id)
        if media is None:
            raise JobFailed("media_missing", "строка медиа удалена")
        if media.kind != "video":
            raise JobFailed("not_video", f"kind={media.kind!r}")
        if media.status != "ready":
            raise JobFailed("media_not_ready", f"статус {media.status!r}")
        settings = await get_settings_dict(db, ctx.spec.tenant_id)
        return media, dict(settings.get("media_storyboard") or {})


def _detect(frames_dir) -> list[float]:
    try:
        detector = faces.FaceDetector()
    except ImportError as exc:
        raise JobFailed("opencv_missing", "opencv-python-headless не установлен в venv") from exc
    files = sorted(frames_dir.glob("f-*.jpg"))
    return faces.ratios_for_frames(files, detector)


async def run(ctx: JobContext) -> JobResult:
    media, params = await _load(ctx)
    thr = float(params.get("face_ratio_thr", 0.12))
    min_len = float(params.get("min_segment_sec", 4))
    bridge = float(params.get("bridge_gap_sec", 2))
    src = absolute_path(media.storage_key)
    if not src.is_file():
        raise JobFailed("source_missing", "файл видео отсутствует в хранилище")
    ctx.set_progress("probe", 0)
    probe = await ctx.probe(src)
    if not probe.has_video:
        raise JobFailed("no_video_stream", "в файле нет видеодорожки")
    duration = float(media.duration_sec or probe.duration or 0.0)
    if duration <= 0:
        raise JobFailed("no_duration", "не удалось определить длительность")
    try:
        storage.ensure_free_space(ctx.settings, int(duration * FRAME_BYTES_PER_SEC) + 2**20)
    except storage.NoSpace as exc:
        raise JobFailed("no_space", str(exc)) from None

    frames_dir = ctx.tmp / "frames"
    frames_dir.mkdir(exist_ok=True)
    await ctx.ffmpeg(
        faces.frames_args(src, frames_dir), stage="frames", duration=duration, pct_scale=0.3
    )
    ctx.set_progress("faces", 30)
    # Каскады — CPU в потоке; heartbeat идёт своим чередом.
    ratios = await asyncio.to_thread(_detect, frames_dir)
    ctx.set_progress("faces", 75)
    cuts_log = await ctx.ffmpeg(
        faces.scene_cut_args(src),
        stage="cuts",
        duration=duration,
        pct_offset=75,
        pct_scale=0.2,
        capture_stderr=True,
        loglevel="info",
    )
    cuts = faces.parse_scene_cuts(cuts_log)
    segments = storyboard.build_segments(
        ratios, duration=duration, thr=thr, min_len=min_len, bridge_gap=bridge, cuts=cuts
    )
    speaker_sec = sum(s["e"] - s["s"] for s in segments if s["kind"] == storyboard.SPEAKER)
    ctx.log.info(
        "media.storyboard_built",
        frames=len(ratios),
        faces_found=sum(1 for r in ratios if r > 0),
        segments=len(segments),
        speaker_sec=round(speaker_sec, 1),
        cuts=len(cuts),
    )
    params_json = {
        "face_ratio_thr": thr,
        "min_segment_sec": min_len,
        "bridge_gap_sec": bridge,
        "cuts": len(cuts),
    }

    async def apply(db: AsyncSession) -> None:
        existing = await db.get(MediaStoryboard, media.id)
        keep_edited = existing is not None and existing.edited_by is not None and existing.segments
        stmt = pg_insert(MediaStoryboard).values(
            media_id=media.id,
            tenant_id=ctx.spec.tenant_id,
            face_track=[round(r, 4) for r in ratios],
            segments_auto=segments,
            segments=segments,
            params=params_json,
        )
        set_: dict[str, Any] = {
            "face_track": stmt.excluded.face_track,
            "segments_auto": stmt.excluded.segments_auto,
            "params": stmt.excluded.params,
        }
        if not keep_edited:
            set_["segments"] = stmt.excluded.segments
        await db.execute(
            stmt.on_conflict_do_update(index_elements=[MediaStoryboard.media_id], set_=set_)
        )

    return JobResult(
        result={
            "frames": len(ratios),
            "faces_found": sum(1 for r in ratios if r > 0),
            "segments": len(segments),
            "speaker_sec": round(speaker_sec, 1),
            "cuts": len(cuts),
            "params": params_json,
        },
        output_media_id=media.id,
        apply=apply,
    )


async def on_final_failure(ctx: JobContext, db: AsyncSession, error: str) -> None:  # noqa: ARG001
    """Видео и чистовик остаются — без раскадровки монтаж просто не предложится."""
