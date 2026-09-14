"""Арифметика повтора задач: где стоит следующий срок.

Отделена от порождения копии (`services/task_recurrence.py`) ради юнит-тестов:
интеграционные в CI не бегут (`pytest -m "not integration"`), а календарная
арифметика — ровно то место, где ошибка тихая и вылезает через месяц.

Два правила, из которых следует всё остальное:

1. **Считаем от ЯКОРЯ серии, а не от предыдущей даты.** Якорь — день срока в
   момент установки правила. Иначе «каждый месяц» от 31 января поплывёт:
   31.01 → 28.02 → 28.03 → 28.04. От якоря получается 31.01 → 28.02 → 31.03.
2. **Берём первый шаг СТРОГО позже сегодня.** Закрыв утреннюю ежедневную
   задачу, человек получает завтрашнюю, а не вторую сегодняшнюю; задача,
   просроченная на месяц, даёт ближайшую будущую дату, а не прошлое.

Работаем календарными днями (`datetime.date`), а не `timedelta` на инстантах:
срок в Hub — календарный день display tz (см. `services/taskdates.py`).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

Freq = Literal["day", "weekday", "week", "month"]

FREQS: tuple[str, ...] = ("day", "weekday", "week", "month")

# Потолок догона: примерно 11 лет ежедневной задачи. Нужен не ради
# производительности, а чтобы битые данные (якорь из 1970-го) не увели цикл
# в бесконечность внутри закрытия задачи.
MAX_CATCHUP_STEPS = 4000


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def advance(anchor: date, freq: str, step: int, k: int) -> date:
    """k-й шаг сетки ОТ ЯКОРЯ (k=0 — сам якорь)."""
    if k <= 0:
        return anchor
    if freq == "day":
        return anchor + timedelta(days=step * k)
    if freq == "week":
        return anchor + timedelta(weeks=step * k)
    if freq == "weekday":
        # step у weekday всегда 1 (CHECK в БД): «каждые три будня» продукт
        # не обещает, а объяснять такое правило человеку нечем.
        d = anchor
        for _ in range(k):
            d += timedelta(days=1)
            while d.weekday() >= 5:  # 5 — суббота, 6 — воскресенье
                d += timedelta(days=1)
        return d
    if freq == "month":
        idx = anchor.year * 12 + (anchor.month - 1) + step * k
        year, month0 = divmod(idx, 12)
        month = month0 + 1
        return date(year, month, min(anchor.day, _days_in_month(year, month)))
    raise ValueError(f"Неизвестная периодичность: {freq}")


def next_occurrence(
    *, freq: str, step: int, anchor: date, occurrence: int, today: date
) -> tuple[date, int]:
    """Первый шаг сетки строго позже `today`. Возвращает (дата, номер шага).

    `occurrence` — сколько шагов уже пройдено: следующий номер всегда больше,
    даже если по датам подошёл бы более ранний.
    """
    k = occurrence + 1
    for _ in range(MAX_CATCHUP_STEPS):
        day = advance(anchor, freq, step, k)
        if day > today:
            return day, k
        k += 1
    raise ValueError(
        "Повтор не смог догнать сегодняшний день — проверьте якорь серии"
    )


def describe(freq: str, step: int) -> str:
    """Человеческая формулировка правила — для ленты, логов и ассистента.

    Зеркало клиентской `web/src/lib/taskRecurrence.ts::describeRecurrence`:
    тексты видит один и тот же человек, и расходиться им нельзя. Числительные
    в ТРИ формы, а не в две: «каждые 21 день», а не «каждые 21 дней».
    """
    if freq == "weekday":
        return "по будням"
    if step <= 1:
        return {"day": "каждый день", "week": "каждую неделю", "month": "каждый месяц"}[freq]
    forms = {
        "day": ("день", "дня", "дней"),
        "week": ("неделю", "недели", "недель"),
        "month": ("месяц", "месяца", "месяцев"),
    }[freq]
    tail, hundred = step % 10, step % 100
    if tail == 1 and hundred != 11:
        word = forms[0]
    elif 2 <= tail <= 4 and not (12 <= hundred <= 14):
        word = forms[1]
    else:
        word = forms[2]
    return f"каждые {step} {word}"
