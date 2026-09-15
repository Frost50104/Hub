"""Ключ проекта из названия — «Подбор линейного персонала» → PLP.

Ключ user-visible: он стоит в номерах задач (PLP-42) и в ссылках. До правки
26.08 `translate` шёл ДО `upper()`, а в таблице транслитерации только заглавные
буквы — поэтому обычное русское название теряло всё, кроме первой буквы, и
проекты подряд получали P, P2, P3…
"""

from __future__ import annotations

import pytest

from app.services.assistant.context import _TASK_KEY_RE
from app.services.personal_projects import PERSONAL_KEY_MAX_LEN, personal_key_base
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


# ─── Ключ личного проекта (16.09) ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        # Оба слова, а не первое: порядок слов в справочнике смешанный, и
        # «первое слово» через раз оказывается именем (замер — 139 против 70).
        ("Пётр Попов", "PETRPOPOV"),
        ("Попов Пётр", "POPOVPETR"),
        # Диграфы: до 16.09 карта давала ZUZGINA и SERBAKOVA.
        ("Жужгина Мария", "ZHUZHGINAMARI"),
        ("Щербакова Анна", "SCHERBAKOVAAN"),
        # Служебные учётки кафе: имя — адрес. Читается лучше, чем LICNOE47.
        ("Гороховая 16", "GOROHOVAYA16"),
        # Отчество отбрасываем — потолок 13 символов жёсткий.
        ("Иванов Иван Иванович", "IVANOVIVAN"),
        # Одно слово — оно и есть база.
        ("Мадонна", "MADONNA"),
        # Нечего транслитерировать — прежний общий ключ.
        ("", "LICNOE"),
        ("   ", "LICNOE"),
        ("1104", "LICNOE"),
        (None, "LICNOE"),
    ],
)
def test_personal_key_base(full_name: str | None, expected: str) -> None:
    assert personal_key_base(full_name) == expected


@pytest.mark.parametrize(
    "full_name",
    ["Константинопольская Александра", "Среднерогатская Кораблестроителей", "Ли Бо"],
)
def test_personal_key_survives_assistant_regex(full_name: str) -> None:
    """Ключ + суффикс обязаны укладываться в регулярку ассистента.

    `_TASK_KEY_RE` матчит «KEY-42» ЦЕЛИКОМ и разрешает 16 символов на ключ, а
    суффикс коллизии клеится ПОСЛЕ среза базы. Импортируем настоящую регулярку,
    а не копию: разъехавшись, модули молча сломали бы резолв «POPOV-42» в чате.
    """
    base = personal_key_base(full_name)
    assert len(base) <= PERSONAL_KEY_MAX_LEN
    assert base.isupper() and base[0].isalpha()
    # Худший случай коллизии — трёхзначный суффикс.
    assert _TASK_KEY_RE.match(f"{base}999-1")
