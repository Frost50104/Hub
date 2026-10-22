"""Воркер конвейера видео (0066) — ОТДЕЛЬНЫЙ systemd-юнит `signaris-hub[-staging]-media`.

Почему не в uvicorn: ffmpeg — CPU на десятки минут. Почему не как extraction:
там работа идёт в открытой транзакции, часовой рендер держал бы соединение
пула. Здесь:

1. claim — одна короткая bypass-транзакция (`jobs.claim_one`, SKIP LOCKED);
2. работа — без транзакций; heartbeat раз в 30 с своей короткой транзакцией
   продлевает аренду, пишет прогресс и читает `cancel_requested`;
3. финал — одна tenant-транзакция: файлы уже на месте (`os.replace`),
   доменные записи обработчика + `jobs.finish`;
4. host-wide `flock` — один ffmpeg на машину (прод и staging делят два ядра);
5. SIGTERM (деплой) — убить ffmpeg, задание обратно в очередь без потери
   попытки (`jobs.release`), выйти.

Выключенный env-рубильник = процесс жив, но спит (юнит active, CPU 0):
так деплой с `try-restart` не ругается, а включение — одна строка в `.env`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import socket
import time
from typing import Any

import structlog

from app import log as log_config
from app.config import Settings, get_settings
from app.db import tenant_scoped_session
from app.services.media import gate, jobs, storage
from app.services.media.jobs import JobSpec
from app.services.media.pipeline import merge_job, normalize_job
from app.services.media.pipeline.context import (
    JobCancelled,
    JobContext,
    JobFailed,
    JobResult,
    bound_logger,
)

log = structlog.get_logger("media.worker")

HEARTBEAT_SEC = 30.0
REAPER_EVERY_SEC = 60.0
FFMPEG_RECHECK_SEC = 60.0

Handler = Any  # модуль с `run(ctx)` и `on_final_failure(ctx, db, error)`
HANDLERS: dict[str, Handler] = {
    normalize_job.KIND: normalize_job,
    merge_job.KIND: merge_job,
}


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


def ffmpeg_available(settings: Settings) -> bool:
    return (
        shutil.which(settings.media_ffmpeg_bin) is not None
        and shutil.which(settings.media_ffprobe_bin) is not None
    )


def classify_failure(exc: BaseException, *, attempts: int, max_attempts: int) -> tuple[str, str]:
    """→ (решение, текст ошибки): `failed` — финал, `retry` — обратно в очередь."""
    if isinstance(exc, JobFailed):
        message = str(exc)
        if exc.final or attempts >= max_attempts:
            return "failed", message
        return "retry", message
    message = f"{type(exc).__name__}: {str(exc)[:300]}"
    if attempts >= max_attempts:
        return "failed", message
    return "retry", message


async def _heartbeat_loop(
    ctx: JobContext, *, lease_sec: int, every: float, stop: asyncio.Event
) -> None:
    """Продлевать аренду и слать прогресс, пока задание идёт; `cancel_requested`
    и остановка воркера взводят `ctx.cancel`. Первый удар — сразу: отмена,
    поставленная до старта, не должна ждать 30 с."""
    while True:
        try:
            async with tenant_scoped_session(None, bypass_rls=True) as db:
                cancel = await jobs.heartbeat(
                    db, ctx.spec.id, lease_sec=lease_sec, progress=dict(ctx.progress)
                )
            if cancel:
                ctx.cancel.set()
                return
        except Exception as exc:  # noqa: BLE001 — heartbeat не роняет задание
            ctx.log.warning("media.heartbeat_failed", err=str(exc)[:200])
        if stop.is_set():
            ctx.cancel.set()
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
            ctx.cancel.set()
            return
        except TimeoutError:
            continue


async def _finish_failed(
    ctx: JobContext, handler: Handler, *, status: str, error: str, result: dict | None = None
) -> None:
    async with tenant_scoped_session(ctx.spec.tenant_id) as db:
        try:
            await handler.on_final_failure(ctx, db, error)
        except Exception as exc:  # noqa: BLE001
            ctx.log.warning("media.on_failure_failed", err=str(exc)[:200])
        await jobs.finish(db, ctx.spec.id, status=status, error=error, result=result)
        await db.commit()


async def run_job(
    spec: JobSpec,
    *,
    settings: Settings,
    stop: asyncio.Event,
    heartbeat_sec: float = HEARTBEAT_SEC,
) -> str:
    """Выполнить уже взятое задание. → итоговый статус (`done|failed|cancelled|
    queued`)."""
    ctx = JobContext(
        spec=spec,
        settings=settings,
        tmp=storage.make_tmp_dir(settings, spec.tenant_id, spec.id),
        cancel=asyncio.Event(),
        log=bound_logger(spec),
    )
    handler = HANDLERS.get(spec.kind)
    started = time.monotonic()
    hb = asyncio.create_task(
        _heartbeat_loop(ctx, lease_sec=settings.media_job_lease_sec, every=heartbeat_sec, stop=stop)
    )
    outcome = "failed"
    try:
        if handler is None:
            raise JobFailed("kind_not_implemented", spec.kind)
        if stop.is_set():
            raise JobCancelled()
        result: JobResult = await handler.run(ctx)
        if ctx.cancel.is_set():
            raise JobCancelled()
        async with tenant_scoped_session(spec.tenant_id) as db:
            if result.apply is not None:
                await result.apply(db)
            await jobs.finish(
                db,
                spec.id,
                status="done",
                result={**result.result, "elapsed_sec": round(time.monotonic() - started, 1)},
                output_media_id=result.output_media_id,
            )
            await db.commit()
        for path in result.cleanup_after_commit:
            path.unlink(missing_ok=True)
        outcome = "done"
        ctx.log.info("media.job_done", elapsed_sec=round(time.monotonic() - started, 1))
    except JobCancelled:
        if stop.is_set():
            async with tenant_scoped_session(None, bypass_rls=True) as db:
                await jobs.release(db, spec.id)
                await db.commit()
            outcome = "queued"
            ctx.log.info("media.job_released")
        else:
            await _finish_failed(
                ctx, handler or normalize_job, status="cancelled", error="cancelled"
            )
            outcome = "cancelled"
            ctx.log.info("media.job_cancelled")
    except Exception as exc:  # noqa: BLE001 — любое падение обработчика классифицируем
        decision, message = classify_failure(
            exc, attempts=spec.attempts, max_attempts=spec.max_attempts
        )
        if decision == "retry":
            async with tenant_scoped_session(None, bypass_rls=True) as db:
                await jobs.retry_later(db, spec.id, error=message)
                await db.commit()
            outcome = "queued"
            ctx.log.warning("media.job_retry", err=message[:300], attempts=spec.attempts)
        else:
            await _finish_failed(ctx, handler or normalize_job, status="failed", error=message)
            outcome = "failed"
            ctx.log.error("media.job_failed", err=message[:300], attempts=spec.attempts)
    finally:
        hb.cancel()
        try:
            await hb
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        storage.remove_tmp_dir(ctx.tmp)
    return outcome


async def run_once(
    *,
    settings: Settings,
    stop: asyncio.Event,
    lock: storage.HostLock,
    worker_id: str,
    heartbeat_sec: float = HEARTBEAT_SEC,
    tenant_id: Any = None,
) -> str | None:
    """Один цикл: замок хоста → claim → работа. → статус задания или None
    (очередь пуста / замок занят)."""
    if not lock.acquire():
        return None
    try:
        async with tenant_scoped_session(None, bypass_rls=True) as db:
            spec = await jobs.claim_one(
                db,
                worker_id=worker_id,
                lease_sec=settings.media_job_lease_sec,
                tenant_id=tenant_id,
            )
        if spec is None:
            return None
        return await run_job(spec, settings=settings, stop=stop, heartbeat_sec=heartbeat_sec)
    finally:
        lock.release()


async def _reap(settings: Settings) -> None:  # noqa: ARG001
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        requeued, failed = await jobs.requeue_expired(db)
    if requeued or failed:
        log.warning("media.reaper", requeued=requeued, failed=failed)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    worker_id = worker_identity()
    lock = storage.HostLock(settings.media_host_lock_path)
    log.info("media.worker_started", worker_id=worker_id, poll_sec=settings.media_worker_poll_sec)
    while not stop.is_set() and not ffmpeg_available(settings):
        log.error("media.ffmpeg_missing", bin=settings.media_ffmpeg_bin)
        await _sleep_or_stop(stop, FFMPEG_RECHECK_SEC)
    try:
        storage.sweep_orphan_tmp(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("media.tmp_sweep_failed", err=str(exc)[:200])
    last_reap = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() - last_reap > REAPER_EVERY_SEC:
                await _reap(settings)
                last_reap = time.monotonic()
            outcome = await run_once(settings=settings, stop=stop, lock=lock, worker_id=worker_id)
        except Exception as exc:  # noqa: BLE001 — цикл живёт всегда
            log.error("media.cycle_failed", err=str(exc)[:300])
            outcome = None
        if outcome is None and not stop.is_set():
            await _sleep_or_stop(stop, settings.media_worker_poll_sec)
    log.info("media.worker_stopped")


async def main() -> None:
    log_config.configure()
    settings = get_settings()
    if not gate.env_enabled():
        log.info("media.worker_disabled", reason="SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED=false")
        while True:
            await asyncio.sleep(3600)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await serve(settings, stop)


if __name__ == "__main__":
    asyncio.run(main())
