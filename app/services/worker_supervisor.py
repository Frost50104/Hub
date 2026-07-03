"""Супервизор фоновых воркеров: рестарт с backoff + Redis-лидерство.

Раньше lifespan запускал воркеры через голый `asyncio.create_task` — падение
воркера оставалось незамеченным до shutdown. Супервизор:

1. Логирует падение и перезапускает воркер с экспоненциальным backoff.
2. Держит Redis-лок лидера (SET NX EX + продление), чтобы при
   `uvicorn --workers N` deletion-sync/sid-sync бежали в ОДНОМ процессе.
   Не-лидеры периодически пробуют перехватить лок — если лидер умер,
   воркер поднимется в другом процессе в пределах TTL.

Если Redis недоступен, лидерство пропускается (деградация к поведению
--workers 1: возможен дубль, но синхронизация не останавливается).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

log = structlog.get_logger("worker_supervisor")

LOCK_TTL_SEC = 60
RENEW_INTERVAL_SEC = 20
ACQUIRE_RETRY_SEC = 30
RESTART_BACKOFF_START_SEC = 5
RESTART_BACKOFF_MAX_SEC = 300

_TOKEN = f"{socket.gethostname()}:{os.getpid()}"

# Compare-and-… — не трогаем чужой лок, если наш TTL успел истечь.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)


def _lock_key(name: str) -> str:
    return f"hub:worker-lock:{name}"


async def supervise(
    name: str, factory: Callable[[], Coroutine[Any, Any, None]]
) -> None:
    """Вечный цикл: взять лидерство → гонять воркер → рестарт после падения.

    Отмена таски супервизора (shutdown) корректно отменяет и воркер:
    factory() ожидается напрямую, CancelledError пробрасывается внутрь.
    """
    backoff = RESTART_BACKOFF_START_SEC
    while True:
        redis = await _try_acquire(name)
        if redis is _NOT_ACQUIRED:
            await asyncio.sleep(ACQUIRE_RETRY_SEC)
            continue

        renewer = (
            asyncio.create_task(_renew_forever(redis, name))
            if redis is not None
            else None
        )
        try:
            log.info("worker.started", worker=name)
            await factory()
            # Воркер вышел сам — это неожиданно, перезапускаем.
            log.warning("worker.exited_unexpectedly", worker=name)
        except asyncio.CancelledError:
            raise  # shutdown приложения
        except Exception:
            log.exception("worker.crashed", worker=name)
        finally:
            if renewer is not None:
                renewer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await renewer
            if redis is not None:
                with contextlib.suppress(Exception):
                    await redis.eval(_RELEASE_LUA, 1, _lock_key(name), _TOKEN)

        log.info("worker.restarting", worker=name, delay_sec=backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX_SEC)


class _NotAcquired:
    pass


_NOT_ACQUIRED = _NotAcquired()


async def _try_acquire(name: str):
    """Redis-клиент лидера, None (Redis недоступен — бежим без лока)
    или _NOT_ACQUIRED (лок держит другой процесс)."""
    from app.redis_client import get_redis

    try:
        redis = get_redis()
        acquired = await redis.set(
            _lock_key(name), _TOKEN, nx=True, ex=LOCK_TTL_SEC
        )
    except Exception as e:  # noqa: BLE001 — деградация без Redis
        log.warning("worker.lock_unavailable", worker=name, err=str(e))
        return None
    return redis if acquired else _NOT_ACQUIRED


async def _renew_forever(redis, name: str) -> None:
    while True:
        await asyncio.sleep(RENEW_INTERVAL_SEC)
        try:
            renewed = await redis.eval(
                _RENEW_LUA, 1, _lock_key(name), _TOKEN, LOCK_TTL_SEC
            )
            if not renewed:
                # Лок истёк и мог уйти другому процессу — редкий случай
                # (Redis flush/долгая пауза): фиксируем, воркер не трогаем.
                log.error("worker.lock_lost", worker=name)
        except Exception as e:  # noqa: BLE001
            log.warning("worker.lock_renew_failed", worker=name, err=str(e))
