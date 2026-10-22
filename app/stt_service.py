"""Отдельный процесс распознавания речи (волна 3 ассистента).

Зачем не в основном приложении: модель `small` держит ~640 МБ и на пике
расшифровки доходит до 741 МБ anon (замер 22.10, `scripts/stt_measure.py`). В
общем процессе OOM-killer выбирал бы жертву сам, и ей не обязательно оказался
бы ассистент: на машине живут Postgres, Redis, два FastAPI и extraction-воркер.
Отдельный юнит с `MemoryMax` превращает нехватку памяти в перезапуск одной
фичи, а сторож systemd (`app/services/stt/watchdog.py`) — зависание тоже.

Слушает 127.0.0.1 и наружу не публикуется: авторизацию делает основное
приложение, сюда приходит уже проверенный запрос.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import sys
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.stt import (
    STTError,
    STTNotConfigured,
    STTTooLong,
    STTUnavailable,
    get_stt,
    local,
    watchdog,
)

log = structlog.get_logger("stt.service")


def _local_enabled() -> bool:
    settings = get_settings()
    return settings.stt_enabled and settings.stt_provider == "local"


_PR_SET_DUMPABLE = 4


def _forbid_core_dumps() -> None:
    """Процесс держит в памяти записи и расшифровки сотрудников — дампу ядра на
    диске им не место. `LimitCORE=0` в юните не спасает: обработчик дампов на
    сервере — apport через pipe, а для pipe ядро этот лимит игнорирует. Учения
    22.10: SIGABRT сторожа оставил в /var/crash отчёт на 175 МБ с дампом, и
    процесс не успел умереть за `TimeoutAbortSec`. Флаг «не дампить» ядро
    проверяет раньше, чем зовёт обработчик."""
    if sys.platform != "linux":
        return
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _forbid_core_dumps()
    tasks: list[asyncio.Task[None]] = []
    if _local_enabled():
        tasks.append(asyncio.create_task(local.preload()))
    interval = watchdog.interval_sec()
    if interval is not None:
        tasks.append(
            asyncio.create_task(
                watchdog.run(local.busy_seconds, get_settings().stt_max_busy_sec, interval=interval)
            )
        )
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Signaris Hub STT", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    """`ready` — 200, остальное — 503: `loading` (идёт загрузка), `missing`
    (модели нет в кэше), `error` (не загрузилась). Читают healthcheck и
    `app.jobs.stt_smoke` после деплоя."""
    if not _local_enabled():
        return JSONResponse({"status": "disabled", "busy_sec": None})
    busy = local.busy_seconds()
    status = local.state()
    return JSONResponse(
        {"status": status, "busy_sec": round(busy, 1) if busy is not None else None},
        status_code=200 if status == "ready" else 503,
    )


@app.post("/transcribe")
async def transcribe(request: Request) -> dict[str, object]:
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="Пустая запись")
    content_type = request.headers.get("content-type", "application/octet-stream")
    try:
        provider = get_stt()
    except STTNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    try:
        if isinstance(provider, local.LocalWhisper):
            result = await provider.transcribe(
                audio, content_type=content_type, is_abandoned=request.is_disconnected
            )
        else:
            result = await provider.transcribe(audio, content_type=content_type)
    except STTTooLong as e:
        raise HTTPException(status_code=413, detail=str(e)) from None
    except STTUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except STTError as e:
        log.warning("stt.failed", error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from None
    return {"text": result.text, "duration_sec": result.duration_sec}


@app.post("/transcribe-segments")
async def transcribe_segments(
    request: Request,
    language: str = "ru",
    beam_size: int = 1,
    word_timestamps: bool = True,
    initial_prompt: str | None = None,
) -> dict[str, object]:
    """Кусок записи урока → сегменты с таймкодами и метриками декодера (0066).
    Только локальный провайдер: удалённый конвейер зовёт сам. Текст в журнал
    не пишется."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="Пустая запись")
    try:
        provider = get_stt()
    except STTNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    if not isinstance(provider, local.LocalWhisper):
        raise HTTPException(status_code=501, detail="Сегменты даёт только локальный провайдер")
    try:
        result = await provider.transcribe_segments(
            audio,
            language=language,
            beam_size=beam_size,
            initial_prompt=(initial_prompt or "")[:500] or None,
            word_timestamps=word_timestamps,
            is_abandoned=request.is_disconnected,
        )
    except STTTooLong as e:
        raise HTTPException(status_code=413, detail=str(e)) from None
    except STTUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except STTError as e:
        log.warning("stt.segments_failed", error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from None
    return {"segments": result.segments, "duration_sec": result.duration_sec}
