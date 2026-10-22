"""Раскадровка: где в кадре человек (→ гусь во весь кадр), где показ экрана
(→ кадр из записи, голос), плюс вставки поверх голоса. Чистая математика над
рядом «доля кадра под самым большим лицом по секундам»; сами лица ищет
`analyze_job` (OpenCV, инкремент 6)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.services.media.edl import EPS, Interval, normalize, subtract

SPEAKER = "speaker"
SCREEN = "screen"
MODES = ("goose", "keep")


def speaker_mask(ratios: Sequence[float], *, thr: float) -> list[bool]:
    """Секунда «спикер в кадре», если лицо занимает ≥ `thr` высоты кадра:
    маленькое лицо в плитке камеры поверх экрана — это показ экрана."""
    return [float(r) >= thr for r in ratios]


def smooth_mask(mask: Sequence[bool], *, window: int = 5) -> list[bool]:
    """Медиана в скользящем окне: единичные промахи детектора не рвут отрезок."""
    n = len(mask)
    if n == 0 or window <= 1:
        return list(mask)
    half = window // 2
    out: list[bool] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        votes = sum(1 for v in mask[lo:hi] if v)
        out.append(votes * 2 > (hi - lo))
    return out


def runs(mask: Sequence[bool]) -> list[Interval]:
    """Непрерывные отрезки True как интервалы секунд `[i, j)`."""
    out: list[Interval] = []
    start: int | None = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((float(start), float(i)))
            start = None
    if start is not None:
        out.append((float(start), float(len(mask))))
    return out


def merge_runs(
    speaker_runs: Iterable[Interval], *, min_len: float, bridge_gap: float
) -> list[Interval]:
    """Склеить отрезки через зазоры ≤ `bridge_gap`, выкинуть короче `min_len`."""
    merged: list[Interval] = []
    for s, e in normalize(speaker_runs):
        if merged and s - merged[-1][1] <= bridge_gap + EPS:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(s, e) for s, e in merged if e - s >= min_len - EPS]


def snap_to_cuts(
    segments: Iterable[Interval], cuts: Sequence[float], *, tolerance: float = 1.5
) -> list[Interval]:
    """Границы подтягиваются к ближайшей смене кадра в пределах `tolerance`."""
    cut_list = sorted(float(c) for c in cuts)

    def snap(t: float) -> float:
        best = None
        for c in cut_list:
            if abs(c - t) <= tolerance and (best is None or abs(c - t) < abs(best - t)):
                best = c
        return t if best is None else best

    out: list[Interval] = []
    for s, e in segments:
        ns, ne = snap(s), snap(e)
        if ne - ns > EPS:
            out.append((ns, ne))
    return normalize(out)


def build_segments(
    ratios: Sequence[float],
    *,
    duration: float,
    thr: float = 0.12,
    min_len: float = 4.0,
    bridge_gap: float = 2.0,
    cuts: Sequence[float] = (),
    smooth_window: int = 5,
) -> list[dict[str, Any]]:
    """Полная раскадровка `[{"s","e","kind","mode"?}]`, покрывающая `[0, duration]`."""
    duration = float(duration)
    mask = smooth_mask(speaker_mask(ratios, thr=thr), window=smooth_window)
    speaker = merge_runs(runs(mask), min_len=min_len, bridge_gap=bridge_gap)
    speaker = [(s, min(e, duration)) for s, e in speaker if s < duration]
    speaker = snap_to_cuts(speaker, cuts) if cuts else speaker
    out: list[dict[str, Any]] = []
    cur = 0.0
    for s, e in speaker:
        if s - cur > EPS:
            out.append({"s": round(cur, 2), "e": round(s, 2), "kind": SCREEN})
        out.append({"s": round(s, 2), "e": round(e, 2), "kind": SPEAKER, "mode": "goose"})
        cur = e
    if duration - cur > EPS:
        out.append({"s": round(cur, 2), "e": round(duration, 2), "kind": SCREEN})
    return out


def validate_segments(
    segments: Iterable[dict[str, Any]], *, duration: float
) -> list[dict[str, Any]]:
    """Отрезки покрывают `[0, duration]` без дыр и пересечений; `kind` из двух;
    `mode` — только у спикера. → нормализованная копия. Ошибка → ValueError."""
    items = sorted(segments, key=lambda x: float(x["s"]))
    out: list[dict[str, Any]] = []
    cur = 0.0
    tol = 0.05
    for seg in items:
        s, e, kind = float(seg["s"]), float(seg["e"]), seg.get("kind")
        if kind not in (SPEAKER, SCREEN):
            raise ValueError(f"Неизвестный вид отрезка: {kind!r}")
        if abs(s - cur) > tol:
            raise ValueError(f"Раскадровка с разрывом около {cur:.1f} с")
        if e - s <= tol:
            raise ValueError(f"Пустой отрезок около {s:.1f} с")
        item: dict[str, Any] = {"s": round(max(cur, s), 2), "e": round(e, 2), "kind": kind}
        if kind == SPEAKER:
            mode = seg.get("mode", "goose")
            if mode not in MODES:
                raise ValueError(f"Неизвестный режим отрезка: {mode!r}")
            item["mode"] = mode
        elif "mode" in seg and seg["mode"] is not None:
            raise ValueError("У показа экрана режима нет")
        out.append(item)
        cur = e
    if abs(cur - float(duration)) > tol:
        raise ValueError("Раскадровка не доходит до конца видео")
    return out


def validate_inserts(inserts: Iterable[dict[str, Any]], *, duration: float) -> list[dict[str, Any]]:
    """Вставки не пересекаются, начинаются внутри видео, длина клампится
    по концу чистовика. → отсортированная копия. Ошибка → ValueError."""
    items = sorted(inserts, key=lambda x: float(x["at"]))
    out: list[dict[str, Any]] = []
    prev_end = -1.0
    for ins in items:
        at, dur = float(ins["at"]), float(ins["duration"])
        if at < 0 or at >= duration - EPS:
            raise ValueError(f"Вставка начинается вне видео: {at:.1f} с")
        if dur <= EPS:
            raise ValueError("Вставка нулевой длины")
        if at < prev_end - EPS:
            raise ValueError(f"Вставки пересекаются около {at:.1f} с")
        end = min(float(duration), at + dur)
        out.append({**ins, "at": round(at, 2), "duration": round(end - at, 2)})
        prev_end = end
    return out


def insert_intervals(inserts: Iterable[dict[str, Any]]) -> list[Interval]:
    return normalize((float(i["at"]), float(i["at"]) + float(i["duration"])) for i in inserts)


def goose_intervals(
    segments: Iterable[dict[str, Any]], inserts: Iterable[dict[str, Any]] = ()
) -> list[Interval]:
    """Где рисует гусь: отрезки спикера в режиме `goose` минус вставки
    (вставка выигрывает, минуты за неё не считаются)."""
    goose = [
        (float(s["s"]), float(s["e"]))
        for s in segments
        if s.get("kind") == SPEAKER and s.get("mode", "goose") == "goose"
    ]
    return subtract(goose, insert_intervals(inserts))
