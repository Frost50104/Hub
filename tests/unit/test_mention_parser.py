"""Грамматика токена упоминания — зеркало `web/src/lib/mentions.ts`.

До 14.09 токеном был только логин почты (`@petr.popov`), и сотрудник
жаловался, что «приходится заходить в почту, смотреть название учётной записи
и уже её вводить через @». Теперь легальны обе формы, и обе обязаны
извлекаться из текста одинаково.
"""

from __future__ import annotations

from app.services.mention_parser import (
    extract_mentions,
    normalize_token,
    render_mentions,
)


class TestExtract:
    def test_имя_и_логин_рядом(self):
        text = "Привет @Иван_Петров и @i.petrov"
        assert extract_mentions(text) == ["иван_петров", "i.petrov"]

    def test_ё_приводится_к_е(self):
        assert extract_mentions("@Семён_Ёлкин") == ["семен_елкин"]

    def test_почта_в_тексте_не_упоминание(self):
        # Граница перед «@» — иначе `ivan@host.ru` дал бы упоминание `@host.ru`.
        assert extract_mentions("пишите на ivan@host.ru") == []
        assert extract_mentions("Привет@ivan") == []

    def test_хвостовая_пунктуация_не_часть_токена(self):
        # «.» и «-» нужны внутри логинов, но в конце это точка предложения.
        assert extract_mentions("позовите @Иван_Петров.") == ["иван_петров"]
        assert extract_mentions("@i.petrov, привет") == ["i.petrov"]

    def test_повторы_схлопываются_с_сохранением_порядка(self):
        text = "@b_b @a_a @b_b"
        assert extract_mentions(text) == ["b_b", "a_a"]

    def test_упоминание_в_начале_строки(self):
        assert extract_mentions("@Иван_Петров, глянь") == ["иван_петров"]

    def test_перевод_строки_обрывает_токен(self):
        assert extract_mentions("@Иван_Петров\nещё текст") == ["иван_петров"]


class TestNormalizeToken:
    def test_регистр_и_хвост(self):
        assert normalize_token("Иван_Петров.") == "иван_петров"
        assert normalize_token("I.Petrov-") == "i.petrov"


class TestRender:
    def test_подставляет_имя(self):
        out = render_mentions("Позовите @Иван_Петров.", {"иван_петров": "Иван Петров"})
        assert out == "Позовите @Иван Петров."

    def test_логин_тоже_становится_именем(self):
        out = render_mentions("@i.petrov, привет", {"i.petrov": "Иван Петров"})
        assert out == "@Иван Петров, привет"

    def test_неизвестный_токен_читается_как_имя(self):
        # Человека удалили — показываем то, что набрали, но без подчёркиваний.
        assert render_mentions("@Иван_Петров!", {}) == "@Иван Петров!"

    def test_текст_без_упоминаний_не_меняется(self):
        assert render_mentions("просто текст", {}) == "просто текст"
