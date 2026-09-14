"""Календарная арифметика повтора — без БД и в CI.

Интеграционные тесты помечены `integration` и в CI не бегут, а здесь ровно тот
класс ошибок, который тихо вылезает через месяц работы: дрейф «каждого месяца»,
31-е число, високосный февраль, выходные и догон просрочки.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.recurrence_dates import advance, describe, next_occurrence


def _chain(anchor: date, freq: str, step: int, count: int) -> list[date]:
    return [advance(anchor, freq, step, k) for k in range(1, count + 1)]


def test_day_and_week_steps():
    anchor = date(2026, 9, 14)
    assert _chain(anchor, "day", 1, 3) == [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)]
    assert _chain(anchor, "day", 3, 2) == [date(2026, 9, 17), date(2026, 9, 20)]
    assert _chain(anchor, "week", 1, 2) == [date(2026, 9, 21), date(2026, 9, 28)]
    assert _chain(anchor, "week", 2, 2) == [date(2026, 9, 28), date(2026, 10, 12)]


def test_month_does_not_drift_from_the_31st():
    """Главная ловушка: считать от ПОДРЕЗАННОЙ даты нельзя.

    31.01 → 28.02 → 31.03 → 30.04 → 31.05. Если бы шаг считался от предыдущего
    значения, после февраля серия навсегда осталась бы на 28-м числе.
    """
    anchor = date(2026, 1, 31)
    assert _chain(anchor, "month", 1, 4) == [
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_month_leap_february():
    assert advance(date(2024, 1, 31), "month", 1, 1) == date(2024, 2, 29)


def test_month_interval_n():
    assert _chain(date(2026, 1, 15), "month", 3, 2) == [date(2026, 4, 15), date(2026, 7, 15)]


def test_weekday_skips_weekend():
    friday = date(2026, 9, 18)
    assert friday.weekday() == 4
    assert advance(friday, "weekday", 1, 1) == date(2026, 9, 21)  # понедельник
    saturday = date(2026, 9, 19)
    assert advance(saturday, "weekday", 1, 1) == date(2026, 9, 21)
    assert _chain(friday, "weekday", 1, 3) == [
        date(2026, 9, 21),
        date(2026, 9, 22),
        date(2026, 9, 23),
    ]


def test_next_is_strictly_after_today():
    """Закрыли ежедневную задачу в её же срок — получаем завтра, не сегодня."""
    today = date(2026, 9, 14)
    day, k = next_occurrence(freq="day", step=1, anchor=today, occurrence=0, today=today)
    assert day == date(2026, 9, 15)
    assert k == 1


def test_catchup_keeps_the_grid():
    """Задача просрочена на месяцы: дата будущая, но сетка сохранена.

    Еженедельная задача со сроком 5 января, закрытая 14 сентября, обязана
    остаться на том же дне недели — иначе «каждый понедельник» сползёт.
    """
    anchor = date(2026, 1, 5)
    today = date(2026, 9, 14)
    day, k = next_occurrence(freq="week", step=1, anchor=anchor, occurrence=0, today=today)
    assert day > today
    assert (day - anchor).days % 7 == 0
    assert day.weekday() == anchor.weekday()
    assert k > 1


def test_occurrence_only_moves_forward():
    """Номер шага монотонен: одна и та же дата дважды не выдаётся."""
    anchor = date(2026, 9, 1)
    today = date(2026, 9, 14)
    first, k1 = next_occurrence(freq="day", step=1, anchor=anchor, occurrence=0, today=today)
    second, k2 = next_occurrence(freq="day", step=1, anchor=anchor, occurrence=k1, today=today)
    assert k2 > k1
    assert second > first


def test_catchup_is_bounded():
    """Битый якорь не должен крутить цикл внутри закрытия задачи."""
    with pytest.raises(ValueError):
        next_occurrence(
            freq="day", step=1, anchor=date(1970, 1, 1), occurrence=0, today=date(2026, 9, 14)
        )


def test_unknown_freq_is_loud():
    with pytest.raises(ValueError):
        advance(date(2026, 9, 14), "year", 1, 1)


@pytest.mark.parametrize(
    ("freq", "step", "expected"),
    [
        ("day", 1, "каждый день"),
        ("weekday", 1, "по будням"),
        ("week", 1, "каждую неделю"),
        ("month", 1, "каждый месяц"),
        ("day", 2, "каждые 2 дня"),
        ("day", 5, "каждые 5 дней"),
        ("week", 2, "каждые 2 недели"),
        ("week", 11, "каждые 11 недель"),
        ("month", 3, "каждые 3 месяца"),
        # 21 — единственное число по-русски: «каждые 21 день», не «дней».
        ("day", 21, "каждые 21 день"),
        ("week", 14, "каждые 14 недель"),
    ],
)
def test_describe(freq: str, step: int, expected: str):
    assert describe(freq, step) == expected
