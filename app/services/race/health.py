"""Здоровье «Гусиной гонки» для `/api/health/race` → `scripts/healthcheck.sh`.

Чистые правила без БД (под юнит-тестом): ручка анонимная, поэтому только коды,
без названий тенантов, чисел и текста ошибок iiko. Снимок по тенанту собирает
`api/env.py`.

До 02.10 гонку не проверял никто: джобы ловят все исключения и выходят с кодом 0,
`OnFailure` у юнитов нет, и сломавшуюся выгрузку заметили бы только по строке
«обновлено N часов назад» на доске.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

# Часовой ритм выгрузки: одна пропущенная (iiko занят) — норма, две подряд — нет.
PULL_STALE_AFTER = timedelta(hours=2)
# Ночное закрытие идёт в 03:45 МСК; к 05:00 `last_close_day` обязан быть «вчера».
CLOSE_EXPECTED_BY_HOUR = 5
# Активирует конкурс часовой тик в 00:40 МСК, а не полночь: до 01:00 дня старта
# «запланирован, но не активен» — норма (ложная тревога 05.10 в 00:01).
ACTIVATION_EXPECTED_BY_HOUR = 1


@dataclass(frozen=True)
class TenantRaceHealth:
    """Снимок тенанта с конкурсом `scheduled|active` (у остальных проверять нечего)."""

    contest_status: str  # scheduled | active
    contest_starts_on: date
    scheduled_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    last_close_day: date | None
    # Число предварительных iiko-баз, чьё окно закрылось по `last_close_day`
    # (закрытие прошло, а финализация — нет).
    preliminary_closed: int


def health_problems(s: TenantRaceHealth, *, now: datetime, tz: tzinfo) -> list[str]:
    """Коды проблем тенанта.

    - `activation_overdue` — конкурс запланирован, старт уже наступил (в день
      старта — после 01:00 МСК, тик активации идёт в 00:40), а он не активен
      (тик не сработал или `race.activate_blocked_by_active`);
    - `pull_stale` — конкурс активен, успешной выгрузки нет дольше 2 часов;
    - `pull_error` — последняя выгрузка активного конкурса упала (очищает только
      успешный `pull_days`);
    - `close_stale` — конкурс активен и был на учёте к ночному закрытию, а
      `last_close_day` после 05:00 МСК всё ещё не «вчера»;
    - `baseline_preliminary` — закрытие прошло, но предварительная база
      активного конкурса не пересчитана (`finalize_baselines` упала).
    """
    local = now.astimezone(tz)
    today = local.date()
    problems: list[str] = []
    if s.contest_status == "scheduled":
        if s.contest_starts_on < today or (
            s.contest_starts_on == today and local.hour >= ACTIVATION_EXPECTED_BY_HOUR
        ):
            problems.append("activation_overdue")
        return problems
    if s.contest_status != "active":
        return problems
    if s.last_success_at is None or now - s.last_success_at > PULL_STALE_AFTER:
        problems.append("pull_stale")
    if s.last_error:
        problems.append("pull_error")
    midnight = datetime.combine(today, time.min, tzinfo=tz)
    on_books_last_night = s.scheduled_at is not None and s.scheduled_at < midnight
    if (
        on_books_last_night
        and local.hour >= CLOSE_EXPECTED_BY_HOUR
        and (s.last_close_day is None or s.last_close_day < today - timedelta(days=1))
    ):
        problems.append("close_stale")
    if s.preliminary_closed > 0:
        problems.append("baseline_preliminary")
    return problems
