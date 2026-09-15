"""Предикаты кросс-проектных списков обязаны компилироваться — без Postgres.

Зачем без контейнера: интеграционные тесты помечены `integration`, а CI гоняет
`pytest -m "not integration"`. Компиляция в диалект Postgres ловит весь класс
`CompileError` и, главное, фиксирует форму условия: EXISTS вместо JOIN (JOIN на
`task_assignees` размножил бы строку задачи) и наличие обеих веток «моего».

Приём и файл-образец — `tests/unit/test_stats_sql_compiles.py`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.project import Project
from app.models.task import Task
from app.services.personal_projects import (
    my_task_scope,
    not_my_personal,
    personal_list_scope,
)

EMPLOYEE = uuid.UUID("79c92fc0-3b0c-46ed-83a0-d40c53d660e3")


def _sql(predicate) -> str:
    stmt = select(Task.id).join(Project, Project.id == Task.project_id).where(predicate)
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_my_task_scope_has_both_branches():
    """«Назначено мне ИЛИ лежит в моём личном» — обе ветки, обе через EXISTS."""
    sql = _sql(my_task_scope(EMPLOYEE))
    assert "EXISTS" in sql
    assert "JOIN task_assignees" not in sql
    # Вторая ветка — без неё личная задача без исполнителей исчезает с экрана.
    assert "projects.personal_owner_id = " in sql
    assert " OR " in sql


def test_my_task_scope_needs_no_join_and_makes_no_cartesian_product():
    """Предикат обязан быть самодостаточным — его кладут в четыре запроса.

    `my_daily_stmt` и `my_created_stmt` в `/me/stats` джойна на `projects` не
    делают. Написанная напрямую ветка `Project.personal_owner_id == me` тихо
    добавляла туда `projects` в FROM декартовым произведением: SQLAlchemy лишь
    предупреждает («cartesian product»), а цифры дня умножались на число
    проектов. Поэтому ветка — коррелированный EXISTS с явным `correlate(Task)`:
    без явной корреляции во внешнем запросе с обеими таблицами подзапрос
    остаётся вовсе без FROM (InvalidRequestError).
    """
    solo = str(
        select(Task.id).where(my_task_scope(EMPLOYEE)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FROM tasks" in solo
    # Единственное упоминание projects — внутри подзапроса, не в FROM внешнего.
    assert "FROM tasks, projects" not in solo
    assert solo.count("FROM projects") == 1

    # И то же выражение переживает внешний запрос, где projects уже приджойнен.
    joined = _sql(my_task_scope(EMPLOYEE))
    assert "JOIN projects" in joined


def test_not_my_personal_still_uses_is_distinct_from():
    """Регресс: `!=` вместо `IS DISTINCT FROM` пропускал бы NULL-владельца."""
    assert "IS DISTINCT FROM" in _sql(not_my_personal(EMPLOYEE))


def test_personal_list_scope_requires_membership():
    """Членство обязательно, иначе строка есть, а карточка 404-ит."""
    sql = _sql(personal_list_scope(EMPLOYEE))
    assert "project_members" in sql
    # Три ветки видимости: обычный проект, моё личное, я причастен к задаче.
    assert "projects.personal_owner_id IS NULL" in sql
    assert "task_watchers" in sql
    assert "task_assignees" in sql


def test_personal_list_scope_has_no_admin_bypass():
    """Ветки hub-admin тут нет и быть не должно.

    `require_project_role` админа мимо членства пропускает, а
    `personal_task_scope` с 15.09 — нет: админ, заведший задачу в чьём-то
    личном и не ставший участником, получил бы строку, которая не открывается.
    Предикат чистый и принимает только employee_id — принципала ему передать
    физически нечем, и это единственная гарантия, которую можно проверить
    статически.
    """
    import inspect

    assert list(inspect.signature(personal_list_scope).parameters) == ["employee_id"]
