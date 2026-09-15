"""Поиск людей по имени: слова в любом порядке, ё→е, токен упоминания.

Регресс, ради которого написано (ОС 14.09): «невозможно написать через @ имя
и фамилию». Поиск шёл ОДНОЙ подстрокой, и на живых данных из 225 двухсловных
ФИО при вводе слов в обратном порядке находилось 0 — при том что порядок в
справочнике смешанный (139 «Имя Фамилия» против 70 «Фамилия Имя»).

SQL здесь не исполняется, а КОМПИЛИРУЕТСЯ: интеграционные тесты в CI не
бегут (`pytest -m "not integration"`), а компиляция ловит весь класс
CompileError без Postgres.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.shadow import ShadowUser
from app.services.people_search import (
    is_token_safe,
    match_condition,
    mention_token_expr,
    name_to_token,
    normalize,
    query_tokens,
    rank_expr,
    token_to_name,
)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestNormalize:
    def test_регистр_пробелы_и_ё(self):
        assert normalize("  Семён   Ёлкин ") == "семен елкин"

    def test_пустая_строка(self):
        assert normalize("   ") == ""


class TestQueryTokens:
    def test_режет_на_слова(self):
        assert query_tokens("Петров Иван") == ["петров", "иван"]

    def test_пустой_запрос(self):
        assert query_tokens(None) == []
        assert query_tokens("   ") == []

    def test_не_больше_четырёх_слов(self):
        assert query_tokens("а б в г д е") == ["а", "б", "в", "г"]


class TestMatchCondition:
    def test_без_запроса_не_фильтруем(self):
        assert match_condition(ShadowUser.full_name, ShadowUser.email, None) is None
        assert match_condition(ShadowUser.full_name, ShadowUser.email, "  ") is None

    def test_каждое_слово_отдельным_условием(self):
        cond = match_condition(ShadowUser.full_name, ShadowUser.email, "петров иван")
        sql = _sql(select(ShadowUser.employee_id).where(cond))
        # Два слова — два LIKE-блока по обеим колонкам, склеенных через AND.
        assert sql.count("LIKE") == 4
        assert " AND " in sql

    def test_ё_нормализуется_в_обе_стороны(self):
        cond = match_condition(ShadowUser.full_name, ShadowUser.email, "Семён")
        sql = _sql(select(ShadowUser.employee_id).where(cond))
        assert "replace" in sql.lower()


class TestRankExpr:
    def test_компилируется_и_с_запросом_и_без(self):
        with_q = _sql(
            select(rank_expr(ShadowUser.full_name, ShadowUser.email, "ив").label("r"))
        )
        assert "CASE" in with_q
        without_q = _sql(
            select(rank_expr(ShadowUser.full_name, ShadowUser.email, None).label("r"))
        )
        assert "CASE" not in without_q


class TestMentionToken:
    def test_безопасное_имя(self):
        assert is_token_safe("Иван Петров")
        assert is_token_safe("Анна-Мария Ким")
        assert is_token_safe("Ivan Petrov")
        assert is_token_safe("Семён Ёлкин")

    def test_непригодное_имя(self):
        # На проде ровно один такой человек — со «/» в ФИО.
        assert not is_token_safe("Иван/Петров")
        assert not is_token_safe("")
        assert not is_token_safe("   ")

    def test_подчёркивание_в_имени_делает_его_непригодным(self):
        # Иначе «Иван_Петров» как ФИО столкнулся бы с токеном тёзки.
        assert not is_token_safe("Иван_Петров")

    def test_туда_и_обратно(self):
        assert name_to_token("  Иван   Петров ") == "Иван_Петров"
        assert token_to_name("Иван_Петров") == "Иван Петров"

    def test_выражение_компилируется(self):
        expr = mention_token_expr(
            ShadowUser.full_name, ShadowUser.email, ShadowUser.hub_role
        )
        sql = _sql(select(expr.label("mention")))
        assert "CASE" in sql
        assert "split_part" in sql
