"""Учёт просмотра видео (Ф3a): merge интервалов + покрытие.

Клиент шлёт просмотренные интервалы [[start, end], …] пингами (~15 сек)
и sendBeacon'ом на pagehide; сервер мёржит их в block_state под FOR UPDATE
(два устройства параллельно — adversarial-ревью §29). «Досмотрено» =
покрытие ≥ WATCH_THRESHOLD длительности — UI-контроль обходим, серверная
проверка интервалов остаётся единственной гарантией (deterrence-модель).
"""

from __future__ import annotations

WATCH_THRESHOLD = 0.9
_MAX_INTERVALS = 500


def merge_intervals(
    existing: list[list[float]], incoming: list[list[float]]
) -> list[list[float]]:
    """Слить интервалы, нормализовав мусор (start>end, отрицательные)."""
    cleaned: list[list[float]] = []
    for pair in [*existing, *incoming][: _MAX_INTERVALS * 2]:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        try:
            start, end = float(pair[0]), float(pair[1])
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start:
            continue
        cleaned.append([start, end])
    cleaned.sort()
    merged: list[list[float]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + 0.5:  # смыкаем щели < 0.5с
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged[:_MAX_INTERVALS]


def coverage(intervals: list[list[float]], duration: float) -> float:
    """Доля просмотренного [0..1]."""
    if duration <= 0:
        return 0.0
    watched = sum(end - start for start, end in intervals)
    return min(1.0, watched / duration)


def is_watched(intervals: list[list[float]], duration: float) -> bool:
    return coverage(intervals, duration) >= WATCH_THRESHOLD
