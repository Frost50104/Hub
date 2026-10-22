"""Здоровье конвейера видео для `/api/health/media` → `scripts/healthcheck.sh`.

Чистые правила без БД под юнит-тестом; снимок собирает `collect_snapshot`
под bypass. Ручка анонимная — только коды, без названий тенантов и текста
ошибок.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.media import MediaJob
from app.services.media import gate

# Задание ждёт в очереди дольше — и при этом ничего не выполняется: воркер стоит.
QUEUE_STALE_AFTER = timedelta(minutes=30)
# Аренда истекла и reaper не вернул задание за 5 минут: воркер и reaper стоят.
LEASE_GRACE = timedelta(minutes=5)
FAILED_BURST = 3
FAILED_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class MediaHealthSnapshot:
    ffmpeg_present: bool
    stt_configured: bool
    avatar_flag: bool  # env `media_avatar_enabled`
    hedra_key_present: bool
    oldest_queued_at: datetime | None
    running_count: int
    expired_running: int  # running с lease_until < now − LEASE_GRACE
    failed_last_24h: int
    hedra_auth_failed: bool  # последнее compose/avatar_test упало `hedra_auth`


def health_problems(s: MediaHealthSnapshot, *, now: datetime) -> list[str]:
    """Коды проблем (ручка анонимная):

    - `ffmpeg_missing` — бинаря нет на машине API; воркер его тоже не найдёт;
    - `stt_unconfigured` — расшифровка `local` без `media_stt_url` (или
      удалённая без ключа): задания `transcribe` будут падать финально;
    - `hedra_key_missing` — флаг гуся включён, ключа нет;
    - `queue_stale` — задание ждёт дольше 30 минут, а `running` нет: воркер не
      берёт очередь (юнит не установлен/упал, flock завис);
    - `lease_expired` — `running` с арендой, истёкшей больше 5 минут назад:
      reaper не работает;
    - `failed_burst` — три и больше провалов за сутки;
    - `hedra_auth` — Hedra отвергла ключ.
    """
    problems: list[str] = []
    if not s.ffmpeg_present:
        problems.append("ffmpeg_missing")
    if not s.stt_configured:
        problems.append("stt_unconfigured")
    if s.avatar_flag and not s.hedra_key_present:
        problems.append("hedra_key_missing")
    if (
        s.oldest_queued_at is not None
        and s.running_count == 0
        and now - s.oldest_queued_at > QUEUE_STALE_AFTER
    ):
        problems.append("queue_stale")
    if s.expired_running > 0:
        problems.append("lease_expired")
    if s.failed_last_24h >= FAILED_BURST:
        problems.append("failed_burst")
    if s.hedra_auth_failed:
        problems.append("hedra_auth")
    return problems


async def collect_snapshot(
    db: AsyncSession, *, settings: Settings, now: datetime | None = None
) -> MediaHealthSnapshot:
    """Снимок очереди под bypass + состояние конфигурации."""
    now = now or datetime.now(UTC)
    oldest_queued = (
        await db.execute(
            select(func.min(MediaJob.created_at)).where(
                MediaJob.status == "queued", MediaJob.run_after <= now
            )
        )
    ).scalar_one()
    running = (
        await db.execute(
            select(func.count()).select_from(MediaJob).where(MediaJob.status == "running")
        )
    ).scalar_one()
    expired = (
        await db.execute(
            select(func.count())
            .select_from(MediaJob)
            .where(MediaJob.status == "running", MediaJob.lease_until < now - LEASE_GRACE)
        )
    ).scalar_one()
    failed = (
        await db.execute(
            select(func.count())
            .select_from(MediaJob)
            .where(MediaJob.status == "failed", MediaJob.finished_at >= now - FAILED_WINDOW)
        )
    ).scalar_one()
    last_hedra = (
        await db.execute(
            select(MediaJob.error)
            .where(MediaJob.kind.in_(("compose", "avatar_test")), MediaJob.status == "failed")
            .order_by(MediaJob.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return MediaHealthSnapshot(
        ffmpeg_present=shutil.which(settings.media_ffmpeg_bin) is not None
        and shutil.which(settings.media_ffprobe_bin) is not None,
        stt_configured=gate.stt_configured(),
        avatar_flag=bool(settings.media_avatar_enabled),
        hedra_key_present=bool(settings.hedra_api_key),
        oldest_queued_at=oldest_queued,
        running_count=int(running or 0),
        expired_running=int(expired or 0),
        failed_last_24h=int(failed or 0),
        hedra_auth_failed=(last_hedra or "").startswith("hedra_auth"),
    )
