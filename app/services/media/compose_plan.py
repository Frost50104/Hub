"""План монтажа (`compose`) — чистая математика: какие отрезки чистовика
заменяются клипами гуся, где поверх голоса идут вставки, как это склеить
одним проходом ffmpeg и сколько секунд уйдёт в Hedra.

Решения владельца 22.10: гусь ЗАМЕНЯЕТ спикера во весь кадр (отрезки
`speaker` в режиме `goose`), на показе экрана — кадр чистовика и только голос;
вставка выигрывает у гуся, её звук отбрасывается, за неё не платят. Звук
всего ролика — целиком из чистовика (без перекодирования стыков).

Склейка — КУСОЧНАЯ, как у сборки из записей: каждый кусок таймлайна рендерится
отдельным ffmpeg в свой mp4 (одни и те же параметры кодека), затем `concat`
demuxer `-c copy`, затем мультиплексирование с аудио чистовика без
перекодирования. Один `-filter_complex` с `trim`+`concat` на часовом чистовике
НЕ годится: ветки `[0:v]trim=…` читают весь вход параллельно, а `concat` копит
кадры поздних веток, пока играет первая, — на 64-минутном монтаже 23.10 ffmpeg
дошёл до 818 МБ anon и был убит OOM cgroup (`MemoryMax=900M`); кусочный
рендер держит память одного x264-энкода (~300 МБ), как у чистовика.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.services.media import chunking, edl, storyboard
from app.services.media.edl import EPS, Interval
from app.services.media.hedra.pricing import billed_seconds, estimate_cost_cents
from app.services.media.merge import concat_list
from app.services.media.normalize import FASTSTART, X264

__all__ = ["concat_list"]

PieceKind = Literal["base", "goose", "insert"]


@dataclass(frozen=True)
class Piece:
    kind: PieceKind
    start: float
    end: float
    # Индекс входа ffmpeg (0 — чистовик) для goose/insert.
    input_index: int = 0
    # Смещение внутри входа: у вставки — с нуля, у клипа гуся — с нуля.
    source_offset: float = 0.0

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class ComposePlan:
    duration: float
    resolution: str
    goose_enabled: bool
    goose: list[Interval]
    chunks: list[Interval]
    inserts: list[dict[str, Any]]
    pieces: list[Piece] = field(default_factory=list)

    @property
    def goose_seconds(self) -> float:
        return edl.total(self.goose)

    @property
    def billed_seconds(self) -> int:
        return billed_seconds(self.chunks)

    @property
    def cost_cents(self) -> int:
        return estimate_cost_cents(self.billed_seconds, self.resolution)

    def summary(self) -> dict[str, Any]:
        return {
            "goose_enabled": self.goose_enabled,
            "goose_seconds": round(self.goose_seconds, 2),
            "chunks": len(self.chunks),
            "billed_seconds": self.billed_seconds,
            "inserts": len(self.inserts),
            "cost_cents": self.cost_cents,
            "resolution": self.resolution,
        }


def plan_compose(
    *,
    duration: float,
    segments: list[dict[str, Any]],
    inserts: list[dict[str, Any]],
    goose_enabled: bool,
    resolution: str,
    transcript_gaps: list[Interval] | None = None,
    chunk_max_sec: float = 600.0,
) -> ComposePlan:
    """Отрезки гуся = `speaker/goose` минус вставки; куски ≤ 10 мин по зазорам
    транскрипта; вставки клампятся по концу чистовика (`validate_inserts`)."""
    clean_inserts = storyboard.validate_inserts(inserts, duration=duration) if inserts else []
    goose = storyboard.goose_intervals(segments, clean_inserts) if goose_enabled else []
    goose = [(s, e) for s, e in goose if e - s >= 0.5]
    chunks = chunking.plan_hedra_chunks(goose, transcript_gaps or [], max_len=chunk_max_sec)
    return ComposePlan(
        duration=float(duration),
        resolution=resolution,
        goose_enabled=goose_enabled,
        goose=goose,
        chunks=chunks,
        inserts=clean_inserts,
    )


def timeline_pieces(
    duration: float,
    chunks: list[Interval],
    inserts: list[dict[str, Any]],
    *,
    first_chunk_input: int,
    first_insert_input: int,
) -> list[Piece]:
    """Разбить `[0, duration]` на куски без дыр: клипы гуся (по одному на
    кусок Hedra), вставки, остальное — кадр чистовика. Вставки и куски гуся по
    построению не пересекаются (гусь считался минус вставки)."""
    marked: list[Piece] = []
    for i, (s, e) in enumerate(chunks):
        marked.append(Piece("goose", s, e, first_chunk_input + i))
    for j, ins in enumerate(inserts):
        at, dur = float(ins["at"]), float(ins["duration"])
        marked.append(Piece("insert", at, min(duration, at + dur), first_insert_input + j))
    marked.sort(key=lambda p: p.start)
    out: list[Piece] = []
    cur = 0.0
    for piece in marked:
        if piece.start - cur > edl.EPS:
            out.append(Piece("base", cur, piece.start))
        if piece.end - max(piece.start, cur) > edl.EPS:
            start = max(piece.start, cur)
            out.append(Piece(piece.kind, start, piece.end, piece.input_index, start - piece.start))
        cur = max(cur, piece.end)
    if duration - cur > edl.EPS:
        out.append(Piece("base", cur, duration))
    return out


def _fit(width: int, height: int, fps: float) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},format=yuv420p"
    )


def piece_args(
    piece: Piece,
    sources: list[Path],
    dst: Path,
    *,
    width: int,
    height: int,
    fps: float,
    threads: int = 1,
) -> list[str]:
    """ffmpeg для ОДНОГО куска таймлайна → mp4 без звука с одинаковыми у всех
    кусков параметрами (иначе `concat -c copy` не склеит). `sources[0]` —
    чистовик, дальше клипы гуся и вставки в порядке `timeline_pieces`.
    Кадр чистовика берётся входной подмоткой `-ss` + `-t` (точно до кадра при
    перекодировании); чужой источник подгоняется под кадр чистовика и
    дотягивается клонированием последнего кадра (`tpad`), если короче."""
    length = piece.length
    src = sources[piece.input_index]
    if piece.kind == "base":
        out: list[str] = ["-ss", f"{piece.start:.3f}", "-i", str(src), "-t", f"{length:.3f}"]
        vf = f"fps={fps:g},format=yuv420p"
    else:
        out = ["-ss", f"{piece.source_offset:.3f}", "-i", str(src), "-t", f"{length:.3f}"]
        vf = f"{_fit(width, height, fps)},tpad=stop_mode=clone:stop_duration={length + 2:.3f}"
    out += ["-an", "-vf", vf, *X264, "-threads", str(threads), str(dst)]
    return out


def concat_video_args(list_path: Path, dst: Path) -> list[str]:
    """Склейка кусков без перекодирования (список — `concat_list`)."""
    return ["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(dst)]


def mux_args(video: Path, cleaned: Path, dst: Path) -> list[str]:
    """Видео склейки + звук чистовика как есть (AAC уже у чистовика) + faststart.
    Звук не режется и не перекодируется — таймлайн монтажа равен чистовику."""
    return [
        "-i",
        str(video),
        "-i",
        str(cleaned),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        *FASTSTART,
        str(dst),
    ]


MUTE_PAD_SEC = 0.15
MUTE_MIN_GAP_SEC = 0.4


def mute_intervals(
    speech: Iterable[Interval],
    start: float,
    end: float,
    *,
    pad: float = MUTE_PAD_SEC,
    min_gap: float = MUTE_MIN_GAP_SEC,
) -> list[Interval]:
    """Что приглушить в голосе куска `[start, end)` (координаты — от начала
    куска): всё вне слов транскрипта с запасом `pad`, только зазоры длиннее
    `min_gap`. Hedra шевелит клюв под любой звук — дыхание, щелчки клавиатуры,
    «пфр» между дублями; без транскрипта (`speech` пуст) не глушим ничего."""
    speech = list(speech)
    if not speech or end - start <= EPS:
        return []
    keep = edl.normalize(
        [
            (max(start, s - pad), min(end, e + pad))
            for s, e in speech
            if e > start - EPS and s < end + EPS
        ]
    )
    gaps = edl.subtract([(start, end)], keep)
    return [(s - start, e - start) for s, e in gaps if e - s >= min_gap - EPS]


def mute_filter(mute: Iterable[Interval]) -> str:
    """`volume` с таймлайном: ноль на приглушаемых отрезках."""
    parts = [f"between(t,{s:.3f},{e:.3f})" for s, e in mute]
    return "volume=0:enable='" + "+".join(parts) + "'"


def voice_slice_args(
    cleaned: Path,
    dst: Path,
    start: float,
    end: float,
    *,
    mute: Iterable[Interval] | None = None,
) -> list[str]:
    """Голос для одного куска Hedra: моно mp3 96k ровно по границам куска;
    `mute` — отрезки без речи (от начала куска), которые глушатся в ноль, чтобы
    гусь молчал в паузах."""
    mute_list = list(mute or [])
    audio_filter = ["-af", mute_filter(mute_list)] if mute_list else []
    return [
        "-ss",
        f"{start:.3f}",
        "-i",
        str(cleaned),
        "-t",
        f"{end - start:.3f}",
        "-vn",
        *audio_filter,
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
        str(dst),
    ]
