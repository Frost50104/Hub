"""One-shot: серверная длительность видео → `media_files.duration_sec` (0043).

Гейт досмотра делит просмотренное на длительность, и до 0043 знаменатель
приходил от клиента: занижение открывает гейт раньше времени, завышение
всего в 1,12 раза делает порог 90% недостижимым навсегда. Файл под media_id
неизменяем, поэтому длительность — физическая константа: читаем её из mp4
один раз (`moov → mvhd`) и храним.

Почему job, а не миграция: чтение файлов с диска не должно валить
`alembic upgrade` (нет файла, битый moov, чужой раздел).

Идемпотентно: без `--recompute` трогает только строки с NULL.

Второй половиной печатает СВЕРКУ с тем, что присылал клиент
(`lesson_progress.block_state.video[*].duration`) — это обязательный шаг
перед тем, как гейт начнёт читать новое поле: если серверное число больше
клиентского, покрытие уже накопленного просядет задним числом. Строки, у
которых из-за подмены знаменателя покрытие падает ниже порога, печатаются
поимённо.

    .venv/bin/python -m app.jobs.backfill_media_duration [--dry-run] [--recompute]
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

import structlog
from sqlalchemy import select

from app import log as log_config
from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.progress import LessonProgress
from app.services.learn_media import absolute_path, mp4_duration_seconds
from app.services.video_progress import WATCH_THRESHOLD, coverage

log = structlog.get_logger("jobs.backfill_media_duration")


async def _tenant_ids() -> list[UUID]:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        rows = await scan.execute(
            select(MediaFile.tenant_id).where(MediaFile.kind == "video").distinct()
        )
        return [r[0] for r in rows]


def _read_durations(files: list[MediaFile]) -> tuple[dict[UUID, float], int, int]:
    """→ (media_id → секунды, нет файла, не распарсилось)."""
    known: dict[UUID, float] = {}
    missing = unreadable = 0
    for media in files:
        try:
            path = absolute_path(media.storage_key)
        except ValueError:  # storage_key вне attachments_root — не наш файл
            missing += 1
            continue
        if not path.is_file():
            # Файл мог быть вычищен вручную: считаем и идём дальше (F2).
            missing += 1
            log.warning("media.file_missing", media_id=str(media.id), key=media.storage_key)
            continue
        seconds = mp4_duration_seconds(path)
        if seconds is None:
            unreadable += 1
            log.warning("media.duration_unreadable", media_id=str(media.id))
            continue
        known[media.id] = seconds
    return known, missing, unreadable


def _compare(
    rows: list[LessonProgress], server: dict[UUID, float]
) -> tuple[int, float, list[str]]:
    """Сверка клиентских длительностей с серверными.

    → (сколько сравнили, максимальное расхождение в секундах, регрессии).
    Регрессия = покрытие было ≥ порога, а с серверным знаменателем стало ниже:
    ровно те люди, у кого «пройдено» превратится в «досмотрите до конца».
    """
    compared = 0
    max_delta = 0.0
    regressions: list[str] = []
    for row in rows:
        videos = (row.block_state or {}).get("video") or {}
        if not isinstance(videos, dict):
            continue
        for raw_id, state in videos.items():
            if not isinstance(state, dict):
                continue
            try:
                media_id = UUID(str(raw_id))
            except ValueError:
                continue
            new = server.get(media_id)
            if new is None:
                continue
            try:
                old = float(state.get("duration") or 0)
            except (TypeError, ValueError):
                continue
            if old <= 0:
                continue
            compared += 1
            max_delta = max(max_delta, abs(new - old))
            intervals = state.get("intervals") or []
            if not isinstance(intervals, list):
                continue
            was = coverage(intervals, old)
            now = coverage(intervals, new)
            if was >= WATCH_THRESHOLD > now:
                regressions.append(
                    f"profile={row.profile_id} lesson={row.lesson_id} media={media_id} "
                    f"{was:.3f}→{now:.3f} (duration {old:.3f}→{new:.3f})"
                )
    return compared, max_delta, regressions


async def main() -> int:
    log_config.configure()
    parser = argparse.ArgumentParser(description="Длительность видео из mp4 в media_files")
    parser.add_argument("--dry-run", action="store_true", help="только отчёт, без записи")
    parser.add_argument(
        "--recompute", action="store_true", help="пересчитать и уже заполненные"
    )
    args = parser.parse_args()

    totals = {"updated": 0, "kept": 0, "missing": 0, "unreadable": 0, "compared": 0}
    max_delta = 0.0
    regressions: list[str] = []

    tenant_ids = await _tenant_ids()
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(tenant_id) as session:
            all_videos = list(
                (
                    await session.execute(
                        select(MediaFile).where(MediaFile.kind == "video")
                    )
                )
                .scalars()
                .all()
            )
            todo = [
                m for m in all_videos if args.recompute or m.duration_sec is None
            ]
            totals["kept"] += len(all_videos) - len(todo)

            known, missing, unreadable = _read_durations(todo)
            totals["missing"] += missing
            totals["unreadable"] += unreadable
            for media in todo:
                seconds = known.get(media.id)
                if seconds is not None and not args.dry_run:
                    media.duration_sec = seconds
            totals["updated"] += len(known)

            # Сверка идёт по ВСЕМ видео тенанта, а не только по обновлённым:
            # смысл в том, чтобы увидеть расхождение до включения гейта.
            server = dict(known)
            for media in all_videos:
                if media.id not in server and media.duration_sec is not None:
                    server[media.id] = media.duration_sec
            progress_rows = list(
                (
                    await session.execute(
                        select(LessonProgress).where(
                            LessonProgress.block_state.has_key("video")
                        )
                    )
                )
                .scalars()
                .all()
            )
            compared, delta, regs = _compare(progress_rows, server)
            totals["compared"] += compared
            max_delta = max(max_delta, delta)
            regressions.extend(regs)

            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()

    log.info(
        "backfill_media_duration.finished",
        tenants=len(tenant_ids),
        dry_run=args.dry_run,
        **totals,
        max_delta_sec=round(max_delta, 4),
        regressions=len(regressions),
    )
    for line in regressions:
        log.warning("coverage.regression", detail=line)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
