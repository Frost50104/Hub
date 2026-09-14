"""Тема оформления: схемы ручки и SQL — без Postgres и в CI.

Интеграционные тесты помечены `integration`, а CI гоняет
`pytest -m "not integration"` — то есть новая ручка `/me/preferences` и селект
темы в `/me` в CI не проверялись бы вовсе. Здесь ловится весь класс поломок,
которому контейнер не нужен: компиляция statement'ов и контракт схем.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.me import MePreferencesUpdate, MeResponse
from app.services.user_prefs import theme_stmt, upsert_theme_stmt

EMPLOYEE = uuid.UUID("79c92fc0-3b0c-46ed-83a0-d40c53d660e3")
TENANT = uuid.UUID("2f2dd1cf-2f0e-4b8f-9d19-4b9ba0f7a6d1")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_select_compiles_and_does_not_filter_tenant_by_hand():
    sql = _sql(theme_stmt(EMPLOYEE))
    assert "user_preferences.theme" in sql
    # RLS фильтрует тенант сам; ручной WHERE сделал бы политику дублирующей.
    assert "tenant_id" not in sql


def test_upsert_compiles_as_on_conflict_by_employee():
    sql = _sql(upsert_theme_stmt(employee_id=EMPLOYEE, tenant_id=TENANT, theme="light"))
    assert "ON CONFLICT (employee_id) DO UPDATE" in sql
    # tenant_id пишется при вставке и НЕ переписывается на конфликте: строка
    # уже принадлежит тенанту, а RLS не дал бы увидеть чужую.
    assert "SET theme" in sql


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_update_schema_accepts_both_themes(theme: str):
    assert MePreferencesUpdate(theme=theme).theme == theme


def test_update_schema_rejects_unknown_theme():
    with pytest.raises(ValidationError):
        MePreferencesUpdate(theme="solarized")


def test_update_schema_forbids_extra_fields():
    """`extra="forbid"`: иначе клиент получил бы 200 на неисполненный запрос."""
    with pytest.raises(ValidationError):
        MePreferencesUpdate(theme="dark", accent="amber")


def test_me_theme_defaults_to_none():
    """None = «выбора нет» → фронт вправе засеять его локальным."""
    assert MeResponse.model_fields["theme"].default is None
