"""Компиляция SQL «Гусиной гонки» под диалект Postgres — страховка на случай,
когда интеграционные тесты не бегут (CI): сломанный Select падает здесь."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.services.race.iiko_pull import lock_tenant_sql
from app.services.race.read import live_positions_stmt


def test_live_positions_groups_by_department_within_window():
    stmt = live_positions_stmt(uuid4(), ["dep-a", "dep-b"], date(2026, 9, 21), date(2026, 9, 27))
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "GROUP BY race_daily_stats.department_id" in sql
    assert "race_daily_stats.day >=" in sql and "race_daily_stats.day <=" in sql
    assert "race_daily_stats.tenant_id =" in sql, "явный tenant_id — джобы читают под bypass"


def test_tenant_lock_is_transactional_advisory_lock():
    assert "pg_advisory_xact_lock" in lock_tenant_sql()
