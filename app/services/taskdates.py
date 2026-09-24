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


def local_time_of(moment: datetime) -> time:
    """Часы и минуты мгновения в display tz (без tzinfo)."""
    return _now(moment).astimezone(display_tz()).time().replace(tzinfo=None)


def at_local(d: date, t: time) -> datetime:
    """День `d` в `t` по display tz → UTC-инстант.

    Для копий по повтору и шаблону со ВРЕМЕНЕМ (0061): «к 15:00» остаётся
    «к 15:00» в новом дне, в том числе через переход на летнее время.
    """
    return datetime.combine(d, t, tzinfo=display_tz()).astimezone(UTC)


class DatePatchError(ValueError):
    """Флаг времени пришёл без самой даты — ручка отвечает 422."""


def resolve_date_patch(
    fields_set: set[str],
    *,
    at_field: str,
    flag_field: str,
    new_at: datetime | None,
    new_flag: bool | None,
) -> tuple[datetime | None, bool] | None:
    """Итоговая пара (мгновение, «задано время») для PATCH/создания (0061).

    None — поле даты не трогали. Правила:
    - дата пришла без флага → флаг `false`: так пишут старые PWA-бандлы, CSV и
      ассистент, которые знают только дни;
    - пришли оба → флаг как прислали, но у снятой даты (`null`) — всегда `false`;
    - флаг без даты → `DatePatchError`: переключать время, не называя момент,
      нельзя — у дня без времени мгновение условное (полдень).

    Пара считается ЦЕЛИКОМ, а не внутри «дата изменилась»: время 12:00 даёт то
    же мгновение, что день без времени, и флаг иначе не записался бы.
    """
    if at_field not in fields_set:
        if flag_field in fields_set:
            raise DatePatchError(at_field)
        return None
    flag = bool(new_flag) if flag_field in fields_set else False
    return new_at, (flag and new_at is not None)


def shift_days(moment: datetime, days: int) -> datetime:
    """Сдвинуть мгновение на `days` КАЛЕНДАРНЫХ дней с тем же часом в display tz.

    Для копирования шаблона (0060): начало задачи «в 10:00» остаётся «в 10:00»
    через границу перехода на летнее время, чего `timedelta(days=...)` в UTC
    не гарантирует. Срок сдвигается отдельно — через `due_noon_utc`.
    """
    if days == 0:
        return moment
    local = _now(moment).astimezone(display_tz())
    shifted = datetime.combine(
        local.date() + timedelta(days=days), local.timetz().replace(tzinfo=None)
    ).replace(tzinfo=display_tz())
    return shifted.astimezone(UTC)


def overdue_days(due_at: datetime, now: datetime | None = None) -> int:
    """Сколько ПОЛНЫХ календарных дней прошло после дня срока (0 — срок сегодня
    или в будущем)."""
    return max(0, (display_today(now) - due_day(due_at)).days)


def is_overdue(due_at: datetime | None, status: str, now: datetime | None = None) -> bool:
    return due_at is not None and status != "done" and due_day(due_at) < display_today(now)


def overdue_clause(now: datetime | None = None) -> ColumnElement[bool]:
    """SQL-условие «просрочена»: день срока раньше сегодняшнего и не done."""
    return and_(Task.due_at < start_of_today_utc(now), Task.done.is_(False))
