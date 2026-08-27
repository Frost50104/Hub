"""Срок задачи = КАЛЕНДАРНЫЙ ДЕНЬ в display tz (settings.display_timezone).

Хранится мгновение (timestamptz), пишется всегда как 12:00 display tz
(`due_noon_utc`), а все сравнения «просрочено / сегодня / предстоит» идут
по границам дня, а не по `now()`: задача со сроком «сегодня» не краснеет в
12:01 и не выпадает из окон «Сегодня»/«Предстоит» (ОС тестировщика, 2026-08).

Все сравнения — с КОНСТАНТНЫМ UTC-инстантом (`due_at < start_of_today_utc()`):
индексы по due_at живут, per-row конверсий таймзоны нет. Когда появится
tenant-tz — менять здесь и в `timefmt.display_tz()`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from app.models.task import Task
from app.services.timefmt import display_tz


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now if now.tzinfo is not None else now.replace(tzinfo=UTC)


def display_today(now: datetime | None = None) -> date:
    return _now(now).astimezone(display_tz()).date()


def day_start_utc(d: date) -> datetime:
    """00:00 display tz указанного дня → UTC-инстант."""
    return datetime.combine(d, time(0, 0), tzinfo=display_tz()).astimezone(UTC)


def start_of_today_utc(now: datetime | None = None) -> datetime:
    return day_start_utc(display_today(now))


def start_of_tomorrow_utc(now: datetime | None = None) -> datetime:
    return day_start_utc(display_today(now) + timedelta(days=1))


def start_of_window_utc(days: int, now: datetime | None = None) -> datetime:
    """Начало окна «последние N дней»: 00:00 дня (сегодня − N + 1) в display tz.

    Именно КАЛЕНДАРНЫЕ дни, а не `now - N*24ч`: человек читает «за 7 дней» как
    «сегодня и шесть предыдущих», и цифра не должна ползти в течение дня. При
    `days=1` окно вырождается в сегодня — совпадает со `start_of_today_utc`.
    """
    return day_start_utc(display_today(now) - timedelta(days=days - 1))


def due_noon_utc(d: date) -> datetime:
    """Единственный писатель «дата → инстант»: полдень display tz."""
    return datetime.combine(d, time(12, 0), tzinfo=display_tz()).astimezone(UTC)


def due_day(due_at: datetime) -> date:
    """Календарный день срока в display tz."""
    return _now(due_at).astimezone(display_tz()).date()


def overdue_days(due_at: datetime, now: datetime | None = None) -> int:
    """Сколько ПОЛНЫХ календарных дней прошло после дня срока (0 — срок сегодня
    или в будущем)."""
    return max(0, (display_today(now) - due_day(due_at)).days)


def is_overdue(due_at: datetime | None, status: str, now: datetime | None = None) -> bool:
    return due_at is not None and status != "done" and due_day(due_at) < display_today(now)


def overdue_clause(now: datetime | None = None) -> ColumnElement[bool]:
    """SQL-условие «просрочена»: день срока раньше сегодняшнего и не done."""
    return and_(Task.due_at < start_of_today_utc(now), Task.done.is_(False))
