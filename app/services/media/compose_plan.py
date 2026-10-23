"""План монтажа (`compose`) — чистая математика: какие отрезки чистовика
заменяются клипами гуся, где поверх голоса идут вставки, как это склеить
одним проходом ffmpeg и сколько секунд уйдёт в Hedra.

Решения владельца 22.10: гусь ЗАМЕНЯЕТ спикера во весь кадр (отрезки
`speaker` в режиме `goose`), на показе экрана — кадр чистовика и только голос;
вставка выигрывает у гуся, её звук отбрасывается, за неё не платят. Звук
всего ролика — целиком из чистовика (без перекодирования стыков).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.services.media import chunking, edl, storyboard
from app.services.media.edl import Interval
from app.services.media.hedra.pricing import billed_seconds, estimate_cost_cents
from app.services.media.normalize import AAC, FASTSTART, X264

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


def filter_script(pieces: list[Piece], *, width: int, height: int, fps: float) -> str:
    """`-filter_complex_script`: каждый кусок — своя ветка, затем `concat`.
    Чужие источники (клип гуся, вставка) подгоняются под кадр чистовика и
    дотягиваются клонированием последнего кадра (`tpad`), если короче."""
    lines: list[str] = []
    labels: list[str] = []
    for n, piece in enumerate(pieces):
        label = f"v{n}"
        if piece.kind == "base":
            lines.append(
                f"[0:v]trim=start={piece.start:.3f}:end={piece.end:.3f},setpts=PTS-STARTPTS[{label}]"
            )
        else:
            length = piece.length
            lines.append(
                f"[{piece.input_index}:v]{_fit(width, height, fps)},"
                f"tpad=stop_mode=clone:stop_duration={length + 2:.3f},"
                f"trim=start={piece.source_offset:.3f}:end={piece.source_offset + length:.3f},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
        labels.append(f"[{label}]")
    lines.append(f"{''.join(labels)}concat=n={len(pieces)}:v=1:a=0[vout]")
    return ";\n".join(lines) + "\n"


def render_args(
    cleaned: Path,
    clips: list[Path],
    insert_files: list[Path],
    script: Path,
    dst: Path,
    *,
    threads: int = 1,
) -> list[str]:
    """Входы: [0] чистовик, затем клипы гуся, затем вставки — в том порядке, в
    каком `timeline_pieces` раздавал индексы. Звук — целиком из чистовика."""
    out: list[str] = ["-i", str(cleaned)]
    for p in [*clips, *insert_files]:
        out += ["-i", str(p)]
    out += [
        "-filter_complex_script",
        str(script),
        "-map",
        "[vout]",
        "-map",
        "0:a:0",
        *X264,
        "-threads",
        str(threads),
        *AAC,
        *FASTSTART,
        str(dst),
    ]
    return out


def voice_slice_args(cleaned: Path, dst: Path, start: float, end: float) -> list[str]:
    """Голос для одного куска Hedra: моно mp3 96k ровно по границам куска."""
    return [
        "-ss",
        f"{start:.3f}",
        "-i",
        str(cleaned),
        "-t",
        f"{end - start:.3f}",
        "-vn",
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
