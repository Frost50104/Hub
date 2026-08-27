"""Запросы статистики обязаны КОМПИЛИРОВАТЬСЯ — без Postgres и в CI.

Зачем отдельно от `tests/integration/test_stats_search.py`: тот помечен
`integration`, а CI гоняет `pytest -m "not integration"` — то есть регресс,
ради которого он написан (`/search` и `/stats` молча ломались апгрейдом
SQLAlchemy), в CI не ловится вообще. Компиляция statement'а в SQL диалекта
Postgres ловит весь класс `CompileError` (NullType в CAST, неразрешимые
перегрузки, битые `label()`) и не требует ни контейнера, ни сети.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.api.stats import my_counters_stmt, my_created_stmt, my_daily_stmt

NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
EMPLOYEE = uuid.UUID("79c92fc0-3b0c-46ed-83a0-d40c53d660e3")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_my_counters_compiles():
    sql = _sql(my_counters_stmt(EMPLOYEE, NOW))
    # Четыре агрегата и EXISTS по исполнителю, а не JOIN: JOIN размножил бы
    # задачу по числу исполнителей.
    assert sql.count("FILTER") == 4
    assert "EXISTS" in sql
    assert "JOIN task_assignees" not in sql


def test_my_created_compiles():
    sql = _sql(my_created_stmt(EMPLOYEE, NOW))
    assert sql.count("FILTER") == 2
    # «Создано» считается по автору, а не по исполнителю — другая популяция.
    assert "created_by" in sql
    assert "EXISTS" not in sql


def test_my_daily_compiles_with_timezone():
    sql = _sql(my_daily_stmt(EMPLOYEE, NOW))
    # Сутки режутся в display tz: без timezone() день переключался бы в
    # 03:00 МСК — ровно та ошибка, что живёт в _completed_trend.
    assert "timezone" in sql
    assert "date_trunc" in sql


def test_windows_are_bounded_on_both_sides():
    """Верхняя граница обязательна: иначе счётчик и график разойдутся."""
    for stmt in (my_counters_stmt(EMPLOYEE, NOW), my_created_stmt(EMPLOYEE, NOW)):
        sql = _sql(stmt)
        assert sql.count(">=") >= 2
        assert sql.count("<") >= 2
