"""Стоимость гуся: локальная таблица цен Hedra Character-3 авторитетна,
`estimate` Hedra лишь сверяет. Считаем ТОЛЬКО отрезки, которые реально
отправятся в Hedra (гусь минус вставки), по кускам с округлением вверх до
секунды — так тарифицирует Hedra."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, tzinfo

from app.schemas.media import HEDRA_CENTS_PER_SEC
from app.services.media.edl import Interval


def billed_seconds(chunks: Iterable[Interval]) -> int:
    return int(sum(math.ceil(max(0.0, e - s) - 1e-9) for s, e in chunks))


def estimate_cost_cents(seconds: float, resolution: str) -> int:
    if resolution not in HEDRA_CENTS_PER_SEC:
        raise ValueError(f"Неизвестное разрешение: {resolution!r}")
    return int(math.ceil(max(0.0, float(seconds)) * HEDRA_CENTS_PER_SEC[resolution] - 1e-9))


def month_bounds(now: datetime, tz: tzinfo) -> tuple[datetime, datetime]:
    """Начало текущего и следующего месяца в display tz (лимит гуся месячный)."""
    local = now.astimezone(tz)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, nxt


def cap_allows(*, cap_minutes: int, used_seconds: float, need_seconds: float) -> bool:
    return used_seconds + need_seconds <= cap_minutes * 60 + 1e-9
