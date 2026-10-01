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

from app.api.stats import (
    leaders_completed_stmt,
    leaders_created_stmt,
    leaders_overdue_stmt,
    my_counters_stmt,
    my_created_stmt,
    my_daily_created_stmt,
    my_daily_stmt,
)

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


def test_archive_filter_touches_only_the_two_now_counters():
    """Половинчатость — не забывчивость, а решение (см. докстринг `_mine`).

    `open_now`/`overdue_now` — состояние на сейчас, они стоят на одном экране
    со списком, из которого архивные проекты ушли. `completed_*` — история:
    фильтр там стирал бы столбики графика за месяцы, когда работа была сделана.
    Поэтому предикат живёт ВНУТРИ двух `.filter()`, а не в общем `where`.
    """
    sql = _sql(my_counters_stmt(EMPLOYEE, NOW))
    assert "JOIN projects" in sql, "джойн нужен: без него предикат не собрать"
    assert sql.count("projects.archived_at IS NULL") == 2
    # Общий WHERE его НЕ несёт — иначе накрыло бы и `completed_*`. Режем по
    # "\nWHERE ", а не по "WHERE": первое вхождение слова — внутри FILTER.
    where = sql.split("\nWHERE ", 1)[1]
    assert "projects.archived_at" not in where


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


def test_my_created_excludes_template_copies():
    # Проект по шаблону на 1 745 задач не должен давать «+1 745 создано» (0060).
    sql = _sql(my_created_stmt(EMPLOYEE, NOW))
    assert "tasks.template_copy IS false" in sql
    assert "tasks.recurrence_parent_id IS NULL" in sql


def test_my_daily_created_compiles_like_daily():
    """Второй ряд графика (01.10): та же сетка суток и те же исключения, что у
    счётчика «создано» — иначе сумма ряда разойдётся с плиткой."""
    sql = _sql(my_daily_created_stmt(EMPLOYEE, NOW))
    assert "timezone" in sql
    assert "date_trunc" in sql
    assert "created_by" in sql
    assert "tasks.template_copy IS false" in sql
    assert "tasks.recurrence_parent_id IS NULL" in sql
    assert sql.count(">=") >= 1 and sql.count("<") >= 1


def test_leaders_exclude_personal_and_service_everywhere():
    """Тенантный рейтинг (01.10): RLS прячет шаблоны, но не личные пространства
    и не кассы — каждый из трёх запросов обязан исключать их сам."""
    for stmt in (
        leaders_completed_stmt(NOW),
        leaders_created_stmt(NOW),
        leaders_overdue_stmt(NOW),
    ):
        sql = _sql(stmt)
        assert "projects.personal_owner_id IS NULL" in sql
        assert "shadow_users.deleted_at IS NULL" in sql
        assert "shadow_users.account_kind IS DISTINCT FROM" in sql
        assert "GROUP BY" in sql


def test_leaders_populations_differ():
    """«Выполнили»/«Просрочено» — по исполнителю (фан-аут задуман), «Создали» —
    по автору без джойна исполнителей: общий запрос размножил бы автора."""
    assert "JOIN task_assignees" in _sql(leaders_completed_stmt(NOW))
    assert "JOIN task_assignees" in _sql(leaders_overdue_stmt(NOW))
    created = _sql(leaders_created_stmt(NOW))
    assert "JOIN task_assignees" not in created
    assert "tasks.created_by" in created
    assert "tasks.template_copy IS false" in created
    assert "tasks.recurrence_parent_id IS NULL" in created


def test_leaders_archive_filter_only_on_overdue():
    """Две истории считают архивные проекты как есть, состояние «сейчас» — нет
    (половинчатое правило `_mine`, перенесённое на команду)."""
    assert "projects.archived_at IS NULL" not in _sql(leaders_completed_stmt(NOW))
    assert "projects.archived_at IS NULL" not in _sql(leaders_created_stmt(NOW))
    overdue = _sql(leaders_overdue_stmt(NOW))
    assert overdue.count("projects.archived_at IS NULL") == 1
    assert "tasks.done IS false" in overdue

