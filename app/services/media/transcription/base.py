"""Типы расшифровки и чистая математика над сегментами: сторож от
галлюцинаций Whisper (пороги из Listen, `pipeline/asr.py`), сшивка кусков,
зазоры транскрипта, сериализация в JSON для `media_transcripts.segments`."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.services.media.edl import Interval

# Пороги Listen (`pipeline/asr.py:32-37`): выше — мусор декодера, не речь.
NO_SPEECH_THRESHOLD = 0.6
LOG_PROB_THRESHOLD = -1.0
COMPRESSION_RATIO_THRESHOLD = 2.4
# Типовые галлюцинации Whisper на тишине/музыке (подписи YouTube-субтитров).
_JUNK = re.compile(
    r"(субтитры\s+(сделал|подготовил|создал)|редактор субтитров|продолжение следует|"
    r"dimatorzok|amara\.org|thank you for watching|подпис(ывайтесь|ка на канал))",
    re.I,
)
# Сшивка через границу куска: зазор меньше — и предыдущий сегмент без
# конечной пунктуации — значит, фразу разрезал кусок, а не пауза.
STITCH_GAP_SEC = 0.3
_SENTENCE_END = (".", "!", "?", "…")


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    words: list[Word] = field(default_factory=list)


@dataclass
class TranscriptResult:
    segments: list[Segment]
    language: str
    duration_sec: float
    provider: str
    model: str


class TranscriptionProvider(Protocol):
    name: str
    model: str

    async def transcribe_file(
        self,
        wav_path: Path,
        *,
        language: str,
        glossary: str,
        beam_size: int,
        on_chunk: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> TranscriptResult: ...


def hallucination_guard(seg: Segment) -> bool:
    """True — сегмент оставляем."""
    text = seg.text.strip()
    if not text or not re.search(r"[\w]", text):
        return False
    if _JUNK.search(text):
        return False
    if seg.compression_ratio is not None and seg.compression_ratio > COMPRESSION_RATIO_THRESHOLD:
        return False
    silent_junk = (
        seg.no_speech_prob is not None
        and seg.avg_logprob is not None
        and seg.no_speech_prob > NO_SPEECH_THRESHOLD
        and seg.avg_logprob < LOG_PROB_THRESHOLD
    )
    return not silent_junk


def offset_segments(segments: Iterable[Segment], offset: float) -> list[Segment]:
    out: list[Segment] = []
    for s in segments:
        out.append(
            Segment(
                start=s.start + offset,
                end=s.end + offset,
                text=s.text,
                avg_logprob=s.avg_logprob,
                no_speech_prob=s.no_speech_prob,
                compression_ratio=s.compression_ratio,
                words=[Word(w.start + offset, w.end + offset, w.text) for w in s.words],
            )
        )
    return out


def stitch(chunks: Sequence[tuple[float, Sequence[Segment]]]) -> list[Segment]:
    """Куски `(смещение, сегменты)` → один ряд. Сегмент, разрезанный границей
    куска, склеивается: зазор < `STITCH_GAP_SEC` и предыдущий без точки."""
    out: list[Segment] = []
    for offset, segs in chunks:
        for seg in offset_segments(segs, offset):
            prev = out[-1] if out else None
            if (
                prev is not None
                and seg.start - prev.end < STITCH_GAP_SEC
                and prev.text.rstrip() != ""
                and not prev.text.rstrip().endswith(_SENTENCE_END)
            ):
                prev.end = max(prev.end, seg.end)
                prev.text = f"{prev.text.rstrip()} {seg.text.lstrip()}"
                prev.words = [*prev.words, *seg.words]
                continue
            out.append(seg)
    return out


def transcript_gaps(
    segments: Iterable[Segment | dict[str, Any]], duration: float
) -> list[Interval]:
    """Зазоры между репликами (и до первой / после последней)."""
    bounds: list[Interval] = []
    for s in segments:
        if isinstance(s, dict):
            bounds.append((float(s["s"]), float(s["e"])))
        else:
            bounds.append((s.start, s.end))
    bounds.sort()
    gaps: list[Interval] = []
    cur = 0.0
    for s, e in bounds:
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if duration > cur:
        gaps.append((cur, float(duration)))
    return gaps


def segments_to_json(segments: Iterable[Segment]) -> list[dict[str, Any]]:
    """Форма `media_transcripts.segments`: `[{"s","e","t","w"?}]`."""
    out: list[dict[str, Any]] = []
    for s in segments:
        item: dict[str, Any] = {"s": round(s.start, 2), "e": round(s.end, 2), "t": s.text.strip()}
        if s.words:
            item["w"] = [[round(w.start, 2), round(w.end, 2), w.text] for w in s.words]
        out.append(item)
    return out


def plain_text(segments: Iterable[Segment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())
