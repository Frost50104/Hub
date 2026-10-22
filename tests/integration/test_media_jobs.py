"""Очередь `media_jobs` (0066): постановка, claim под SKIP LOCKED, аренда,
heartbeat, финиш, reaper, учёт минут гуся, RLS.

Строки коммитятся: claim идёт из ДРУГИХ (bypass) сессий, как у воркера.
Все выборки claim фильтруются `tenant_id` теста — общая БД контейнера.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import tenant_scoped_session
from app.models.course import MediaFile
from app.models.media import MediaJob
from app.services.media import jobs

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _engine_per_test(_fresh_engine):
    """Сессии здесь открываются вручную: без сброса движка пул держал бы
    соединения петли предыдущего теста («attached to a different loop»)."""
    yield


async def _media(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_scoped_session(tenant_id) as db:
        media = MediaFile(
            tenant_id=tenant_id,
            kind="video",
            storage_key=f"{tenant_id}/learn/media/{uuid.uuid4()}-x.mp4",
            file_name="x.mp4",
            mime="video/mp4",
            size_bytes=1,
            duration_sec=60.0,
        )
        db.add(media)
        await db.commit()
        return media.id


async def _enqueue(tenant_id, media_id, kind, **kw) -> uuid.UUID:
    async with tenant_scoped_session(tenant_id) as db:
        job = await jobs.enqueue(db, tenant_id=tenant_id, media_id=media_id, kind=kind, **kw)
        await db.commit()
        return job.id


async def _job(tenant_id, job_id) -> MediaJob:
    async with tenant_scoped_session(tenant_id) as db:
        return (await db.execute(select(MediaJob).where(MediaJob.id == job_id))).scalar_one()


async def _claim(tenant_id, **kw):
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        return await jobs.claim_one(
            db, worker_id="test:1", lease_sec=kw.pop("lease_sec", 900), tenant_id=tenant_id, **kw
        )


async def test_duplicate_active_job_conflicts_until_finished(tenant_id):
    media_id = await _media(tenant_id)
    first = await _enqueue(tenant_id, media_id, "transcribe")
    async with tenant_scoped_session(tenant_id) as db:
        with pytest.raises(jobs.JobConflict):
            await jobs.enqueue(db, tenant_id=tenant_id, media_id=media_id, kind="transcribe")
        # Транзакция пережила ошибку UNIQUE (savepoint): другой вид ставится.
        await jobs.enqueue(db, tenant_id=tenant_id, media_id=media_id, kind="cleanup")
        await db.commit()
    async with tenant_scoped_session(tenant_id) as db:
        await jobs.finish(db, first, status="done")
        await db.commit()
    await _enqueue(tenant_id, media_id, "transcribe")
    with pytest.raises(ValueError, match="Неизвестный вид"):
        await _enqueue(tenant_id, media_id, "explode")


async def test_claim_respects_priority_and_skip_locked(tenant_id):
    a, b = await _media(tenant_id), await _media(tenant_id)
    cleanup = await _enqueue(tenant_id, a, "cleanup")
    normalize = await _enqueue(tenant_id, b, "normalize")
    later = await _enqueue(tenant_id, a, "transcribe", priority=5)
    async with tenant_scoped_session(tenant_id) as db:
        job = (await db.execute(select(MediaJob).where(MediaJob.id == later))).scalar_one()
        job.run_after = datetime.now(UTC) + timedelta(hours=1)
        await db.commit()

    # Два «воркера» держат транзакции одновременно: SKIP LOCKED даёт разные строки.
    async with (
        tenant_scoped_session(None, bypass_rls=True) as w1,
        tenant_scoped_session(None, bypass_rls=True) as w2,
    ):
        stmt = (
            select(MediaJob)
            .where(MediaJob.tenant_id == tenant_id, MediaJob.status == "queued")
            .where(MediaJob.run_after <= datetime.now(UTC))
            .order_by(MediaJob.priority, MediaJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        locked = (await w1.execute(stmt)).scalar_one()
        assert locked.id == normalize, "priority 10 раньше 100"
        other = (await w2.execute(stmt)).scalar_one()
        assert other.id == cleanup, "занятую строку второй воркер пропустил"
        await w1.rollback()
        await w2.rollback()

    spec = await _claim(tenant_id)
    assert spec is not None and spec.id == normalize and spec.kind == "normalize"
    assert spec.attempts == 1 and spec.max_attempts == 2
    row = await _job(tenant_id, normalize)
    assert row.status == "running" and row.worker_id == "test:1"
    assert row.lease_until is not None and row.started_at is not None

    spec2 = await _claim(tenant_id)
    assert spec2 is not None and spec2.id == cleanup
    assert await _claim(tenant_id) is None, "третье задание ещё не подошло по run_after"


async def test_heartbeat_progress_cancel_and_finish_merge(tenant_id):
    media_id = await _media(tenant_id)
    job_id = await _enqueue(tenant_id, media_id, "cleanup", params={"min_pause_sec": 1.5})
    spec = await _claim(tenant_id)
    assert spec is not None and spec.params == {"min_pause_sec": 1.5}

    async with tenant_scoped_session(None, bypass_rls=True) as db:
        stop = await jobs.heartbeat(
            db, job_id, lease_sec=900, progress={"stage": "render", "pct": 42}
        )
    assert stop is False
    row = await _job(tenant_id, job_id)
    assert row.result["progress"]["pct"] == 42 and "updated_at" in row.result["progress"]

    async with tenant_scoped_session(tenant_id) as db:
        job = (await db.execute(select(MediaJob).where(MediaJob.id == job_id))).scalar_one()
        assert await jobs.cancel(db, job) == "cancel_requested"
        await db.commit()
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        assert await jobs.heartbeat(db, job_id, lease_sec=900) is True

    async with tenant_scoped_session(tenant_id) as db:
        await jobs.finish(db, job_id, status="done", result={"stats": {"pauses": 3}})
        await db.commit()
    row = await _job(tenant_id, job_id)
    assert row.status == "done" and row.finished_at is not None and row.lease_until is None
    assert row.result["progress"]["pct"] == 42, "финиш сливает result, а не перезаписывает"
    assert row.result["stats"] == {"pauses": 3}

    # Отмена очередного задания — сразу терминальная.
    queued = await _enqueue(tenant_id, media_id, "transcribe")
    async with tenant_scoped_session(tenant_id) as db:
        job = (await db.execute(select(MediaJob).where(MediaJob.id == queued))).scalar_one()
        assert await jobs.cancel(db, job) == "cancelled"
        await db.commit()
    assert (await _job(tenant_id, queued)).status == "cancelled"
    # heartbeat по исчезнувшему из running заданию = «стоп».
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        assert await jobs.heartbeat(db, queued, lease_sec=10) is True


async def test_reaper_requeues_expired_lease_then_fails_on_last_attempt(tenant_id):
    media_id = await _media(tenant_id)
    job_id = await _enqueue(tenant_id, media_id, "merge")
    assert (await _claim(tenant_id, lease_sec=60)) is not None

    far = datetime.now(UTC) + timedelta(hours=1)
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        requeued, failed = await jobs.requeue_expired(db, now=far, tenant_id=tenant_id)
    assert (requeued, failed) == (1, 0)
    row = await _job(tenant_id, job_id)
    assert row.status == "queued" and row.error == "lease_expired"
    assert row.run_after == far + jobs.REQUEUE_DELAY and row.worker_id is None

    spec = await _claim(tenant_id, lease_sec=60, now=row.run_after)
    assert spec is not None and spec.attempts == 2
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        requeued, failed = await jobs.requeue_expired(
            db, now=far + timedelta(hours=2), tenant_id=tenant_id
        )
    assert (requeued, failed) == (0, 1), "попытки кончились — failed"
    assert (await _job(tenant_id, job_id)).status == "failed"


async def test_monthly_avatar_seconds_counts_reserve_then_fact(tenant_id, rls_enforced):
    """Под RLS: суперпользователь тестов видел бы задания всех тенантов."""
    media_id = await _media(tenant_id)
    compose = await _enqueue(tenant_id, media_id, "compose", params={"estimated_seconds": 120})
    await _enqueue(tenant_id, media_id, "cleanup", params={"estimated_seconds": 999})
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with tenant_scoped_session(tenant_id) as db:
        assert await jobs.monthly_avatar_seconds(db, month_start=month_start) == 120
        await jobs.finish(db, compose, status="done", result={"billed_seconds": 90})
        await db.commit()
        assert await jobs.monthly_avatar_seconds(db, month_start=month_start) == 90
        assert await jobs.count_active(db) == 1


async def test_rls_hides_other_tenants_jobs(tenant_id, rls_enforced):
    media_id = await _media(tenant_id)
    await _enqueue(tenant_id, media_id, "transcribe")
    async with tenant_scoped_session(tenant_id) as db:
        assert await jobs.count_active(db) == 1
    async with tenant_scoped_session(uuid.uuid4()) as other:
        assert await jobs.count_active(other) == 0
