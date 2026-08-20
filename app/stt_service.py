"""Отдельный процесс распознавания речи (волна 3 ассистента).

Зачем не в основном приложении: замерено на этом VPS (2 vCPU, 1.9 ГБ RAM,
swap нет) — модель `small` даёт пик 759 МБ при ~1.1 ГБ свободных. В общем
процессе OOM-killer выбирал бы жертву сам, и ей не обязательно оказался бы
ассистент: на машине живут Postgres, Redis, два FastAPI и extraction-воркер.
Отдельный юнит с `MemoryMax` превращает нехватку памяти в понятную ошибку
одной фичи вместо падения продукта.

Слушает 127.0.0.1 и наружу не публикуется: авторизацию делает основное
приложение, сюда приходит уже проверенный запрос.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request

from app.config import get_settings
from app.services.stt import STTError, STTNotConfigured, get_stt

log = structlog.get_logger("stt.service")

_UNLOAD_POLL_SEC = 60.0


async def _idle_unloader() -> None:
    """Возвращает память, когда голосом давно не пользовались."""
    from app.services.stt.local import unload_if_idle

    idle = get_settings().stt_idle_unload_sec
    while True:
        await asyncio.sleep(_UNLOAD_POLL_SEC)
        with contextlib.suppress(Exception):
            unload_if_idle(idle)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_idle_unloader())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Signaris Hub STT", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
        result = await provider.transcribe(audio, content_type=content_type)
    except STTError as e:
        log.warning("stt.failed", error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from None
    return {"text": result.text, "duration_sec": result.duration_sec}
