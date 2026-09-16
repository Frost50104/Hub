"""Запросы «Прогресса сотрудников» обязаны КОМПИЛИРОВАТЬСЯ — без Postgres и в CI.

Зеркало `test_stats_sql_compiles.py` и по той же причине: интеграционные тесты
помечены `integration`, а CI гоняет `pytest -m "not integration"`. Компиляция
под диалект Postgres ловит весь класс `CompileError` и не требует контейнера.

Сверх компиляции здесь закреплены три инварианта, каждый из которых уже
однажды стоил ошибки:

* JOIN прогресса к `courses` — без него в счётчики попадали архивные и
  черновые курсы (тот самый дефект, ради которого написан сервис);
* отсутствие ПРЕДИКАТА по `tenant_id` — фильтрует RLS, ручное условие сделало
  бы его бесполезным дублем (колонка в SELECT при этом законна: модель её
  несёт);
* тай-брейкер по `id` в сортировке людей — без него порядок между одинаковыми
  ФИО не воспроизводится.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql

from app.services.learning_progress import (
    assignments_stmt,
    audience_membership_stmt,
    certificates_count_stmt,
    lesson_counts_stmt,
    points_stmt,
    profiles_stmt,
    progress_rows_stmt,
    published_courses_stmt,
    quizzes_passed_stmt,
)

IDS = [uuid.UUID("79c92fc0-3b0c-46ed-83a0-d40c53d660e3")]
AUDS = [uuid.UUID("2b4b2f2a-4c1e-4c6e-9a0e-1f2c3d4e5f60")]


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _all_statements() -> dict[str, object]:
    return {
        "profiles": profiles_stmt(IDS),
        "courses": published_courses_stmt(),
        "membership": audience_membership_stmt(IDS, AUDS),
        "assignments": assignments_stmt(IDS),
        "progress": progress_rows_stmt(IDS),
        "quizzes": quizzes_passed_stmt(IDS),
        "certificates": certificates_count_stmt(IDS),
        "points": points_stmt(IDS),
        "lessons": lesson_counts_stmt(IDS),
    }


def test_every_statement_compiles():
    for name, stmt in _all_statements().items():
        assert _sql(stmt), name


def test_no_manual_tenant_predicate():
    """RLS делает это сам — ручное условие превратило бы его в дубль."""
    for name, stmt in _all_statements().items():
        sql = _sql(stmt)
        assert "tenant_id =" not in sql, name
        assert "tenant_id IN" not in sql, name


def test_progress_is_joined_to_published_courses():
    """Регрессия на дефект: без JOIN считались архивные и черновые курсы."""
    sql = _sql(progress_rows_stmt(IDS))
    assert "JOIN courses" in sql
    assert "courses.status" in sql


def test_assignments_are_joined_to_published_courses():
    sql = _sql(assignments_stmt(IDS))
    assert "JOIN courses" in sql
    assert "courses.status" in sql


def test_profiles_order_has_id_tiebreaker():
    sql = _sql(profiles_stmt(IDS))
    order_by = sql.split("ORDER BY")[-1]
    assert "employee_profiles.full_name" in order_by
    assert "employee_profiles.id" in order_by


def test_quizzes_passed_counts_distinct_quizzes():
    """Пересдача одного теста не должна считаться второй раз.

    SQLAlchemy рендерит `func.distinct` строчными — `count(distinct(...))`;
    для Postgres это та же агрегатная форма `COUNT(DISTINCT ...)`, поэтому
    сверяем без учёта регистра.
    """
    sql = _sql(quizzes_passed_stmt(IDS)).lower()
    assert "count(distinct(" in sql


def test_lesson_counts_take_published_lessons_only():
    sql = _sql(lesson_counts_stmt(IDS))
    assert "course_lessons.status" in sql


def test_empty_id_list_still_compiles():
    """Пустой скоуп — рабочее состояние (ТУ без закреплённых магазинов)."""
    for stmt in (
        progress_rows_stmt([]),
        quizzes_passed_stmt([]),
        certificates_count_stmt([]),
        points_stmt([]),
        assignments_stmt([]),
        audience_membership_stmt([], []),
    ):
        assert _sql(stmt)


def test_filters_reach_the_where_clause():
    sql = _sql(
        profiles_stmt(
            IDS,
            q="петров",
            store_id=IDS[0],
            position_id=IDS[0],
        )
    )
    assert "employee_profiles.store_id =" in sql
    assert "employee_profiles.position_id =" in sql
    # Пословный поиск разворачивается в LIKE по ФИО и почте.
    assert "lower" in sql.lower()
