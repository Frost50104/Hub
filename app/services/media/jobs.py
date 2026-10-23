"""Очередь заданий конвейера (`media_jobs`): постановка, claim, аренда, финиш.

Правила, ради которых это отдельный модуль, а не копия extraction-воркера:
- claim — ОДНА короткая bypass-транзакция `FOR UPDATE SKIP LOCKED` → `running`
  → commit (образец `task_reminders.tick`); дальше ни одной открытой
  транзакции на время CPU-работы — часовой рендер в открытой транзакции
  держал бы соединение пула и блокировки;
- живость задания — аренда `lease_until`, которую продлевает heartbeat своей
  короткой транзакцией; просроченная аренда (воркер убит посреди рендера)
  возвращает задание в очередь, пока есть попытки;
- одно активное задание вида на медиа — частичный UNIQUE в БД, API получает
  `JobConflict` → 409 «уже выполняется»;
- `result` сливается (`||`), а не перезаписывается: `compose` хранит там
  состояние Hedra по кускам и после рестарта не платит дважды.

Все функции принимают сессию снаружи и НЕ коммитят, кроме тех, что названы
явно (`claim_one`, `heartbeat`, `requeue_expired` — воркерные, со своими
короткими транзакциями под bypass).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Float, and_, cast, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import ACTIVE_JOB_STATUSES, JOB_KINDS, JOB_PRIORITY, MediaJob

FINAL_STATUSES: tuple[str, ...] = ("done", "failed", "cancelled")
# Воркер вернул задание в очередь (аренда истекла или SIGTERM) — не сразу,
# чтобы упавший на этом задании процесс не крутил его без пауз.
REQUEUE_DELAY = timedelta(minutes=1)


class JobConflict(Exception):
    """Активное задание этого вида на этом медиа уже есть."""


@dataclass(frozen=True)
class JobSpec:
    """Снимок задания для воркера — без ORM-объекта и без открытой транзакции."""

    id: UUID
    tenant_id: UUID
    media_id: UUID
    kind: str
    params: dict[str, Any]
    attempts: int
    max_attempts: int
    requested_by: UUID | None


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def enqueue(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    media_id: UUID,
    kind: str,
    params: dict[str, Any] | None = None,
    requested_by: UUID | None = None,
    priority: int | None = None,
    max_attempts: int = 2,
) -> MediaJob:
    """Поставить задание. Дубликат активного → `JobConflict` (savepoint, чтобы
    транзакция вызывающего пережила ошибку UNIQUE)."""
    if kind not in JOB_KINDS:
        raise ValueError(f"Неизвестный вид задания: {kind!r}")
    job = MediaJob(
        id=uuid4(),
        tenant_id=tenant_id,
        media_id=media_id,
        kind=kind,
        status="queued",
        params=dict(params or {}),
        result={},
        attempts=0,
        max_attempts=max_attempts,
        priority=JOB_PRIORITY.get(kind, 100) if priority is None else priority,
        requested_by=requested_by,
    )
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError as exc:
        if "uq_media_jobs_active" in str(exc.orig):
            raise JobConflict(kind) from None
        raise
    return job


async def active_job(db: AsyncSession, media_id: UUID, kind: str) -> MediaJob | None:
    return (
        await db.execute(
            select(MediaJob).where(
                MediaJob.media_id == media_id,
                MediaJob.kind == kind,
                MediaJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def claim_one(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_sec: int,
    now: datetime | None = None,
    tenant_id: UUID | None = None,
) -> JobSpec | None:
    """Взять одно задание: `queued`, срок подошёл, по приоритету и возрасту.

    Сессия — bypass (очередь общая на все тенанты). Коммитит сама: аренда
    должна быть видна reaper'у и API сразу. `tenant_id` — только для тестов
    на общей БД.
    """
    now = _now(now)
    stmt = (
        select(MediaJob)
        .where(MediaJob.status == "queued", MediaJob.run_after <= now)
        .order_by(MediaJob.priority, MediaJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if tenant_id is not None:
        stmt = stmt.where(MediaJob.tenant_id == tenant_id)
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        await db.rollback()
        return None
    job.status = "running"
    job.attempts += 1
    job.started_at = now
    job.lease_until = now + timedelta(seconds=lease_sec)
    job.worker_id = worker_id
    job.error = None
    spec = JobSpec(
        id=job.id,
        tenant_id=job.tenant_id,
        media_id=job.media_id,
        kind=job.kind,
        params=dict(job.params or {}),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        requested_by=job.requested_by,
    )
    await db.commit()
    return spec


async def heartbeat(
    db: AsyncSession,
    job_id: UUID,
    *,
    lease_sec: int,
    progress: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> bool:
    """Продлить аренду и записать прогресс. → `cancel_requested` (воркер
    прерывает работу). Коммитит сама — это отдельная короткая транзакция."""
    now = _now(now)
    values: dict[str, Any] = {"lease_until": now + timedelta(seconds=lease_sec)}
    if progress is not None:
        # Словарь, а не json.dumps: bind-процессор JSONB сериализует сам, строка
        # уехала бы в jsonb как JSON-строка.
        payload = {**progress, "updated_at": now.isoformat()}
        values["result"] = func.jsonb_set(
            MediaJob.result, literal_column("'{progress}'"), cast(payload, JSONB), True
        )
    row = (
        await db.execute(
            update(MediaJob)
            .where(MediaJob.id == job_id, MediaJob.status == "running")
            .values(**values)
            .returning(MediaJob.cancel_requested)
        )
    ).scalar_one_or_none()
    await db.commit()
    # Строки нет (задание отменили/перепоставили из-под воркера) — тоже «стоп».
    return True if row is None else bool(row)


async def finish(
    db: AsyncSession,
    job_id: UUID,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    output_media_id: UUID | None = None,
    now: datetime | None = None,
) -> None:
    """Терминальное состояние. `result` сливается с накопленным."""
    if status not in FINAL_STATUSES:
        raise ValueError(f"finish: не терминальный статус {status!r}")
    now = _now(now)
    values: dict[str, Any] = {
        "status": status,
        "finished_at": now,
        "lease_until": None,
        "error": (error or "")[:2000] or None,
    }
    if output_media_id is not None:
        values["output_media_id"] = output_media_id
    if result:
        values["result"] = MediaJob.result.op("||")(cast(result, JSONB))
    await db.execute(update(MediaJob).where(MediaJob.id == job_id).values(**values))


async def retry_later(
    db: AsyncSession,
    job_id: UUID,
    *,
    error: str,
    delay: timedelta = REQUEUE_DELAY,
    now: datetime | None = None,
    carry_params: dict[str, Any] | None = None,
) -> None:
    """Вернуть в очередь после неудачи, у которой остались попытки."""
    now = _now(now)
    values: dict[str, Any] = {
        "status": "queued",
        "run_after": now + delay,
        "lease_until": None,
        "worker_id": None,
        "error": error[:2000],
    }
    if carry_params is not None:
        values["params"] = carry_params
    await db.execute(update(MediaJob).where(MediaJob.id == job_id).values(**values))


async def release(
    db: AsyncSession,
    job_id: UUID,
    *,
    now: datetime | None = None,
    carry_params: dict[str, Any] | None = None,
) -> None:
    """Воркер останавливается (SIGTERM при деплое): вернуть задание в очередь
    СРАЗУ и не считать попытку — это не провал задания. `carry_params` —
    состояние для возобновления (куски Hedra), если есть."""
    now = _now(now)
    values: dict[str, Any] = {
        "status": "queued",
        "run_after": now,
        "lease_until": None,
        "worker_id": None,
        "attempts": func.greatest(MediaJob.attempts - 1, 0),
        "error": "worker_stopped",
    }
    if carry_params is not None:
        values["params"] = carry_params
    await db.execute(
        update(MediaJob).where(MediaJob.id == job_id, MediaJob.status == "running").values(**values)
    )


async def list_for_media(
    db: AsyncSession, media_ids: list[UUID], *, limit: int = 20
) -> list[MediaJob]:
    """Последние задания по набору медиа (само видео + производные)."""
    if not media_ids:
        return []
    return list(
        (
            await db.execute(
                select(MediaJob)
                .where(MediaJob.media_id.in_(media_ids))
                .order_by(MediaJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def requeue_expired(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    delay: timedelta = REQUEUE_DELAY,
    tenant_id: UUID | None = None,
) -> tuple[int, int]:
    """Reaper: `running` с истёкшей арендой → `queued` (есть попытки) или
    `failed`. → (возвращено, провалено). Bypass-сессия, коммитит сама.
    `tenant_id` — только для тестов на общей БД."""
    now = _now(now)
    expired = and_(MediaJob.status == "running", MediaJob.lease_until < now)
    if tenant_id is not None:
        expired = and_(expired, MediaJob.tenant_id == tenant_id)
    requeued = (
        await db.execute(
            update(MediaJob)
            .where(expired, MediaJob.attempts < MediaJob.max_attempts)
            .values(
                status="queued",
                run_after=now + delay,
                lease_until=None,
                worker_id=None,
                error="lease_expired",
            )
            .returning(MediaJob.id)
        )
    ).all()
    failed = (
        await db.execute(
            update(MediaJob)
            .where(expired)
            .values(status="failed", finished_at=now, lease_until=None, error="lease_expired")
            .returning(MediaJob.id)
        )
    ).all()
    await db.commit()
    return len(requeued), len(failed)


async def cancel(db: AsyncSession, job: MediaJob, *, now: datetime | None = None) -> str:
    """`queued` → `cancelled` сразу; `running` → флаг, воркер остановит сам.
    → новый статус (для ответа API)."""
    now = _now(now)
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = now
        job.error = "cancelled"
        return "cancelled"
    if job.status == "running":
        job.cancel_requested = True
        return "cancel_requested"
    return job.status


async def count_active(db: AsyncSession) -> int:
    """Активные задания тенанта (сессия tenant-scoped — RLS режет сама)."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(MediaJob)
                .where(MediaJob.status.in_(ACTIVE_JOB_STATUSES))
            )
        ).scalar_one()
    )


async def monthly_avatar_seconds(db: AsyncSession, *, month_start: datetime) -> float:
    """Секунды гуся, занятые в этом месяце: по факту (`result.billed_seconds`),
    иначе по резерву заказа (`params.estimated_seconds`). Считаются `queued`,
    `running` и `done` — резерв списывается при постановке."""
    billed = func.coalesce(
        cast(MediaJob.result["billed_seconds"].astext, Float),
        cast(MediaJob.params["estimated_seconds"].astext, Float),
        0.0,
    )
    total = (
        await db.execute(
            select(func.coalesce(func.sum(billed), 0.0)).where(
                MediaJob.kind.in_(("compose", "avatar_test")),
                MediaJob.status.in_(("queued", "running", "done")),
                MediaJob.created_at >= month_start,
            )
        )
    ).scalar_one()
    return float(total or 0.0)
