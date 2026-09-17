"""Человекочитаемые даты/время для уведомлений и экспортов.

Все timestamptz в БД — UTC; людям (push, Inbox, CSV) показываем локальное
время сети из `settings.display_timezone` (default Europe/Moscow — сеть
UPPETIT). Tenant-tz в модели нет (см. calendar.py) — когда появится, менять
ТОЛЬКО здесь. Naive datetime считаем UTC (так пишут джобы и тесты).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
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


_MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def fmt_day(d: date) -> str:
    """«21 сентября» — для календарной даты без времени (учётный день iiko)."""
    return f"{d.day} {_MONTHS_GEN[d.month - 1]}"


def fmt_day_range(a: date, b: date) -> str:
    """«21–27 сентября», «28 сентября — 4 октября», один день — «21 сентября»."""
    if a == b:
        return fmt_day(a)
    if a.month == b.month and a.year == b.year:
        return f"{a.day}–{b.day} {_MONTHS_GEN[b.month - 1]}"
    return f"{fmt_day(a)} — {fmt_day(b)}"
