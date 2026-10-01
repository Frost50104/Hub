"""Ранжирование «Команды за 30 дней» — чистая функция, без базы."""

from __future__ import annotations

import uuid

from app.api.stats import rank_leaders

ME = uuid.uuid4()


def _row(name: str | None, count: int, email: str | None = "x@test.ru", eid=None):
    return (eid or uuid.uuid4(), name, email, count)


def test_top_three_by_count_then_name_without_gaps():
    rows = [
        _row("Яна", 5),
        _row("Анна", 7),
        _row("борис", 7),
        _row("Вера", 7),
        _row("Глеб", 1),
    ]
    top, _me = rank_leaders(rows, ME)
    assert [(lead.full_name, lead.rank) for lead in top] == [
        ("Анна", 1),
        ("борис", 2),
        ("Вера", 3),
    ]


def test_me_outside_top_keeps_rank_and_count():
    rows = [_row("А", 9), _row("Б", 8), _row("В", 7), _row("Я", 2, eid=ME), _row("Д", 3)]
    top, me = rank_leaders(rows, ME)
    assert len(top) == 3
    assert me is not None and (me.rank, me.count) == (5, 2)


def test_zero_rows_drop_out_and_me_is_none():
    rows = [_row("А", 0, eid=ME), _row("Б", 2)]
    top, me = rank_leaders(rows, ME)
    assert [lead.full_name for lead in top] == ["Б"]
    assert me is None


def test_name_falls_back_to_email_then_dash():
    rows = [_row(None, 3, email="noname@test.ru"), _row(None, 2, email=None)]
    top, _ = rank_leaders(rows, ME)
    assert [lead.full_name for lead in top] == ["noname@test.ru", "—"]
