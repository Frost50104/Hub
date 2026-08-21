"""Человекочитаемые даты/время для уведомлений и экспортов.

Все timestamptz в БД — UTC; людям (push, Inbox, CSV) показываем локальное
время сети из `settings.display_timezone` (default Europe/Moscow — сеть
UPPETIT). Tenant-tz в модели нет (см. calendar.py) — когда появится, менять
ТОЛЬКО здесь. Naive datetime считаем UTC (так пишут джобы и тесты).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import get_settings


@lru_cache(maxsize=4)
def _tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def display_tz() -> ZoneInfo:
    return _tz(get_settings().display_timezone)


def to_display(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(display_tz())


def fmt_dt(dt: datetime, fmt: str) -> str:
    return to_display(dt).strftime(fmt)


def fmt_date(dt: datetime) -> str:
    """«30.08.2026»."""
    return fmt_dt(dt, "%d.%m.%Y")


def fmt_range(start: datetime, end: datetime) -> str:
    """«30.08 10:00–18:00»; если конец в другой день — «30.08 22:00–31.08 06:00»."""
    s = to_display(start)
    e = to_display(end)
    if s.date() == e.date():
        return f"{s.strftime('%d.%m %H:%M')}–{e.strftime('%H:%M')}"
    return f"{s.strftime('%d.%m %H:%M')}–{e.strftime('%d.%m %H:%M')}"
