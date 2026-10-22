"""Список монтажных решений чистовика (EDL): паузы → удаляемые куски →
оставшиеся интервалы → перемаппинг таймкодов.

Всё чистое и под юнит-тестами: CI без ffmpeg. Интервалы — пары секунд
`(start, end)`, полуоткрытые по смыслу, но сравниваются с допуском `EPS`.

Решение владельца 22.10: паузы УЖИМАЮТСЯ, а не вырезаются. У паузы `[a, b]`
длиннее `min_pause` удаляется середина `[a + h, b − h]`, `h = max(margin,
keep / 2)`: остаётся ~`keep` секунд тишины, речь не слипается, а показ экрана
не дёргается. Пауза короче порога не трогается вовсе.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

Interval = tuple[float, float]

EPS = 1e-6


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    """Отсортировать, выкинуть пустые, слить пересекающиеся и смежные."""
    items = sorted((float(s), float(e)) for s, e in intervals if e - s > EPS)
    out: list[Interval] = []
    for s, e in items:
        if out and s <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def intersect(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    """Пересечение двух наборов интервалов (оба нормализуются)."""
    xs, ys = normalize(a), normalize(b)
    out: list[Interval] = []
    i = j = 0
    while i < len(xs) and j < len(ys):
        s = max(xs[i][0], ys[j][0])
        e = min(xs[i][1], ys[j][1])
        if e - s > EPS:
            out.append((s, e))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    """`a` минус `b`."""
    out: list[Interval] = []
    cuts = normalize(b)
    for s, e in normalize(a):
        cur = s
        for cs, ce in cuts:
            if ce <= cur + EPS:
                continue
            if cs >= e - EPS:
                break
            if cs > cur + EPS:
                out.append((cur, cs))
            cur = max(cur, ce)
        if e - cur > EPS:
            out.append((cur, e))
    return out


def total(intervals: Iterable[Interval]) -> float:
    return float(sum(e - s for s, e in normalize(intervals)))


def pauses(
    silences: Iterable[Interval],
    gaps: Iterable[Interval] | None,
    *,
    min_pause: float,
) -> list[Interval]:
    """Паузы = тишина по звуку ∩ зазоры транскрипта (тихая речь не режется),
    длиннее `min_pause`. Без транскрипта (`gaps=None`) — только тишина."""
    base = normalize(silences) if gaps is None else intersect(silences, gaps)
    return [(s, e) for s, e in base if e - s >= min_pause - EPS]


def compress_pauses(
    pause_list: Iterable[Interval], *, keep: float, margin: float
) -> list[Interval]:
    """Удаляемые куски: середина каждой паузы, края остаются."""
    h = max(float(margin), float(keep) / 2.0)
    removed: list[Interval] = []
    for a, b in normalize(pause_list):
        s, e = a + h, b - h
        if e - s > EPS:
            removed.append((s, e))
    return removed


def kept_intervals(removed: Iterable[Interval], duration: float) -> list[Interval]:
    """Дополнение удалённого внутри `[0, duration]`."""
    return subtract([(0.0, float(duration))], removed)


def remap_time(t: float, removed: Sequence[Interval]) -> float:
    """Время исходника → время чистовика. Точка внутри удалённого куска
    приклеивается к его началу."""
    shift = 0.0
    for s, e in removed:
        if t <= s + EPS:
            break
        if t < e:
            return max(0.0, s - shift)
        shift += e - s
    return max(0.0, t - shift)


def remap_segments(
    segments: Iterable[dict[str, Any]],
    removed: Sequence[Interval],
    *,
    min_len: float = 0.05,
) -> list[dict[str, Any]]:
    """Перемапить `[{"s","e","t","w"?}]` транскрипта; схлопнувшиеся выкинуть."""
    removed = normalize(removed)
    out: list[dict[str, Any]] = []
    for seg in segments:
        s = remap_time(float(seg["s"]), removed)
        e = remap_time(float(seg["e"]), removed)
        if e - s < min_len:
            continue
        item: dict[str, Any] = {**seg, "s": round(s, 3), "e": round(e, 3)}
        if seg.get("w"):
            words = []
            for ws, we, wt in seg["w"]:
                ns, ne = remap_time(float(ws), removed), remap_time(float(we), removed)
                if ne - ns >= 0.0:
                    words.append([round(ns, 3), round(ne, 3), wt])
            item["w"] = words
        out.append(item)
    return out


def select_expr(kept: Iterable[Interval]) -> str:
    """Выражение для `select`/`aselect`: сумма `between(t,s,e)`."""
    parts = [f"between(t,{s:.3f},{e:.3f})" for s, e in normalize(kept)]
    return "+".join(parts) if parts else "0"
