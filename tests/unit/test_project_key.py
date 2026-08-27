"""Ключ проекта из названия — «Подбор линейного персонала» → PLP.

Ключ user-visible: он стоит в номерах задач (PLP-42) и в ссылках. До правки
26.08 `translate` шёл ДО `upper()`, а в таблице транслитерации только заглавные
буквы — поэтому обычное русское название теряло всё, кроме первой буквы, и
проекты подряд получали P, P2, P3…
"""

from __future__ import annotations

import pytest

from app.services.project_key import _candidate


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Реальные проекты прода: их ключи выданы этой же функцией и совпадают.
        ("Подбор линейного персонала", "PLP"),
        ("Игра франчайзи", "IF"),
        ("Отдел маркетинга", "OM"),
        ("На удаление", "NU"),
        # Одно слово — первые буквы, а не инициал.
        ("Ёлка", "ELKA"),
        # Латиница работала и раньше — регресс-страховка.
        ("Marketing Team", "MT"),
        # Не больше четырёх инициалов.
        ("Раз два три четыре пять", "RDTC"),
        # Ключ обязан начинаться с буквы: ведущая цифра отбрасывается.
        ("1С обмен", "O"),
        # Ни одной пригодной буквы — фолбэк.
        ("   ", "PROJ"),
        ("!!!", "PROJ"),
    ],
)
def test_candidate(name: str, expected: str) -> None:
    assert _candidate(name) == expected


def test_candidate_always_starts_with_letter_and_fits_column() -> None:
    for name in ("Подбор", "1С", "—", "Ё", "Очень длинное название проекта тут"):
        key = _candidate(name)
        assert key[0].isalpha() and key.isupper()
        assert len(key) <= 16  # запас под числовой суффикс до лимита 32
