"""Расшифровка через наш STT-юнит (`app/stt_service.py`, ручка
`/transcribe-segments`) кусками ≤ `media_stt_chunk_sec`.

Юнит один на хост и держит один запрос за раз: между кусками пауза
`media_stt_pause_sec`, чтобы голосовая команда ассистента вклинилась в FIFO.
503 (модель грузится / юнит занят / запрос отменён) — подождать и повторить
кусок, 413 — наш план нарезки ошибся (финальная ошибка), 5xx/сеть — повтор
с нарастающей паузой, потом ошибка."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.services.media import chunking
from app.services.media.edl import Interval
from app.services.media.transcription.base import (
    Segment,
    TranscriptResult,
    Word,
    hallucination_guard,
    stitch,
)

log = structlog.get_logger("media.transcription.local")

RETRY_503_SEC = (5.0, 15.0, 30.0, 60.0, 120.0)
RETRY_ERR_SEC = (3.0, 10.0, 30.0)


class TranscriptionError(RuntimeError):
    def __init__(self, code: str, message: str = "", *, final: bool = False) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message
        self.final = final


def segment_from_json(item: dict[str, Any]) -> Segment:
    words = [Word(float(w[0]), float(w[1]), str(w[2])) for w in item.get("w") or []]
    return Segment(
        start=float(item["s"]),
        end=float(item["e"]),
        text=str(item.get("t") or ""),
        avg_logprob=item.get("avg_logprob"),
        no_speech_prob=item.get("no_speech_prob"),
        compression_ratio=item.get("compression_ratio"),
        words=words,
    )


class LocalUnitProvider:
    name = "local"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        chunk_sec: float = 55.0,
        pause_sec: float = 1.0,
        timeout_sec: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.chunk_sec = chunk_sec
        self.pause_sec = pause_sec
        self.timeout_sec = timeout_sec
        self._transport = transport
        self._sleep = sleep

    def plan(self, duration: float, silences: list[Interval]) -> list[Interval]:
        return chunking.plan_chunks(
            duration,
            silences,
            target=max(10.0, self.chunk_sec - 5.0),
            max_len=self.chunk_sec,
            min_len=min(20.0, self.chunk_sec / 2),
        )

    async def _post_chunk(
        self,
        client: httpx.AsyncClient,
        blob: bytes,
        *,
        language: str,
        glossary: str,
        beam_size: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "language": language,
            "beam_size": beam_size,
            "word_timestamps": "true",
        }
        if glossary:
            params["initial_prompt"] = glossary[:500]
        busy_waits = 0
        err_waits = 0
        while True:
            try:
                resp = await client.post(
                    f"{self.base_url}/transcribe-segments",
                    params=params,
                    content=blob,
                    headers={"Content-Type": "audio/wav"},
                )
            except httpx.HTTPError as exc:
                if err_waits >= len(RETRY_ERR_SEC):
                    raise TranscriptionError("stt_unreachable", type(exc).__name__) from exc
                await self._sleep(RETRY_ERR_SEC[err_waits])
                err_waits += 1
                continue
            if resp.status_code == 200:
                try:
                    return list(resp.json()["segments"])
                except (ValueError, KeyError, TypeError) as exc:
                    raise TranscriptionError("stt_bad_response", str(exc)[:100]) from None
            if resp.status_code == 503:
                if busy_waits >= len(RETRY_503_SEC):
                    raise TranscriptionError("stt_busy", resp.text[:200])
                await self._sleep(RETRY_503_SEC[busy_waits])
                busy_waits += 1
                continue
            if resp.status_code == 413:
                raise TranscriptionError("chunk_too_long", resp.text[:200], final=True)
            if resp.status_code in (404, 501):
                # Юнит без ручки: прод-STT ещё на старом коде.
                raise TranscriptionError("stt_no_segments_route", resp.text[:200], final=True)
            if resp.status_code >= 500:
                if err_waits >= len(RETRY_ERR_SEC):
                    raise TranscriptionError("stt_error", f"{resp.status_code} {resp.text[:200]}")
                await self._sleep(RETRY_ERR_SEC[err_waits])
                err_waits += 1
                continue
            raise TranscriptionError(
                "stt_error", f"{resp.status_code} {resp.text[:200]}", final=True
            )

    async def transcribe_file(
        self,
        wav_path: Path,
        *,
        language: str,
        glossary: str,
        beam_size: int,
        duration: float,
        silences: list[Interval],
        on_chunk: Callable[[int, int], Awaitable[None]] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> TranscriptResult:
        plan = self.plan(duration, silences)
        chunks: list[tuple[float, list[Segment]]] = []
        async with httpx.AsyncClient(timeout=self.timeout_sec, transport=self._transport) as client:
            for i, (blob, (start, _end)) in enumerate(
                zip(chunking.read_wav_slices(wav_path, plan), plan, strict=True)
            ):
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError("cancelled", final=True)
                raw = await self._post_chunk(
                    client, blob, language=language, glossary=glossary, beam_size=beam_size
                )
                segs = [segment_from_json(item) for item in raw]
                kept = [s for s in segs if hallucination_guard(s)]
                if len(kept) != len(segs):
                    log.info("media.stt_guard_dropped", chunk=i, dropped=len(segs) - len(kept))
                chunks.append((start, kept))
                if on_chunk is not None:
                    await on_chunk(i + 1, len(plan))
                if i + 1 < len(plan) and self.pause_sec > 0:
                    await self._sleep(self.pause_sec)
        return TranscriptResult(
            segments=stitch(chunks),
            language=language,
            duration_sec=duration,
            provider=self.name,
            model=self.model,
        )
