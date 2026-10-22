"""Удалённый OpenAI-совместимый Whisper (`/audio/transcriptions`,
`response_format=verbose_json`) — опция по env для сравнения качества с
локальным `small`. Файл режется на куски ≤ 10 минут по тишине (лимит тела
25 МБ у совместимых API; WAV 16 кГц моно — 1,9 МБ/мин)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.services.media import chunking
from app.services.media.edl import Interval
from app.services.media.transcription.base import (
    Segment,
    TranscriptResult,
    Word,
    hallucination_guard,
    stitch,
)
from app.services.media.transcription.local_unit import TranscriptionError

CHUNK_MAX_SEC = 600.0
CHUNK_MIN_SEC = 120.0


def parse_verbose_json(data: dict[str, Any]) -> list[Segment]:
    """`verbose_json` → сегменты; слова (если `timestamp_granularities=word`)
    раскладываются по сегментам по времени."""
    words_raw = data.get("words") or []
    words = [
        Word(float(w["start"]), float(w["end"]), str(w.get("word") or "").strip())
        for w in words_raw
        if "start" in w and "end" in w
    ]
    out: list[Segment] = []
    for item in data.get("segments") or []:
        start, end = float(item["start"]), float(item["end"])
        seg_words = [w for w in words if w.start >= start - 1e-3 and w.end <= end + 1e-3]
        out.append(
            Segment(
                start=start,
                end=end,
                text=str(item.get("text") or "").strip(),
                avg_logprob=item.get("avg_logprob"),
                no_speech_prob=item.get("no_speech_prob"),
                compression_ratio=item.get("compression_ratio"),
                words=seg_words,
            )
        )
    if not out and data.get("text"):
        out.append(
            Segment(start=0.0, end=float(data.get("duration") or 0.0), text=str(data["text"]))
        )
    return out


class OpenAICompatProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_sec: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self._transport = transport

    async def transcribe_file(
        self,
        wav_path: Path,
        *,
        language: str,
        glossary: str,
        beam_size: int,  # noqa: ARG002 — у удалённого API параметра нет
        duration: float,
        silences: list[Interval],
        on_chunk: Callable[[int, int], Awaitable[None]] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> TranscriptResult:
        plan = chunking.plan_chunks(
            duration,
            silences,
            target=CHUNK_MAX_SEC - 30,
            max_len=CHUNK_MAX_SEC,
            min_len=CHUNK_MIN_SEC,
        )
        chunks: list[tuple[float, list[Segment]]] = []
        async with httpx.AsyncClient(timeout=self.timeout_sec, transport=self._transport) as client:
            for i, (blob, (start, _end)) in enumerate(
                zip(chunking.read_wav_slices(wav_path, plan), plan, strict=True)
            ):
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError("cancelled", final=True)
                data = {
                    "model": self.model,
                    "language": language,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                }
                if glossary:
                    data["prompt"] = glossary[:500]
                try:
                    resp = await client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self._key}"},
                        files={"file": ("chunk.wav", blob, "audio/wav")},
                        data=data,
                    )
                except httpx.HTTPError as exc:
                    raise TranscriptionError("stt_unreachable", type(exc).__name__) from exc
                if resp.status_code == 401:
                    raise TranscriptionError("stt_auth", resp.text[:200], final=True)
                if resp.status_code != 200:
                    raise TranscriptionError(
                        "stt_error",
                        f"{resp.status_code} {resp.text[:200]}",
                        final=resp.status_code < 500,
                    )
                try:
                    segs = parse_verbose_json(resp.json())
                except (ValueError, KeyError, TypeError) as exc:
                    raise TranscriptionError("stt_bad_response", str(exc)[:100]) from None
                chunks.append((start, [s for s in segs if hallucination_guard(s)]))
                if on_chunk is not None:
                    await on_chunk(i + 1, len(plan))
        return TranscriptResult(
            segments=stitch(chunks),
            language=language,
            duration_sec=duration,
            provider=self.name,
            model=self.model,
        )
