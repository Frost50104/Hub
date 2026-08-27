"""Валидатор бейджа-эмодзи.

Интеграционные тесты в CI не бегут, поэтому единственная реальная защита этого
кода — здесь. Проверяем не «работает ли регулярка», а конкретные способы, по
которым она ломается: `$` вместо `\\Z`, забытая проверка длины, разрешённый
одиночный regional indicator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectBadgeUpdate

# Каждый — ОДИН пользовательски воспринимаемый символ.
ACCEPTED = [
    pytest.param("\U0001f680", id="одиночный-пиктограф"),
    pytest.param("⌚", id="часы-из-старого-диапазона"),
    pytest.param("❤️", id="сердце-с-VS16"),
    pytest.param("✅", id="галочка"),
    pytest.param("\U0001f44d\U0001f3fd", id="палец-с-тоном-кожи"),
    pytest.param("\U0001f469‍\U0001f4bb", id="ZWJ-профессия"),
    pytest.param(
        "\U0001f468‍\U0001f469‍\U0001f467‍\U0001f466", id="ZWJ-семья"
    ),
    pytest.param("\U0001f3f3️‍\U0001f308", id="радужный-флаг"),
    pytest.param("\U0001f9d1\U0001f3fe‍\U0001f680", id="ZWJ-плюс-тон"),
    pytest.param("\U0001f1f7\U0001f1fa", id="флаг-парой-regional-indicator"),
    pytest.param(
        "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
        id="флаг-субдивизии-tag-sequence",
    ),
    pytest.param("1️⃣", id="keycap-цифра"),
    pytest.param("#️⃣", id="keycap-решётка"),
]

REJECTED = [
    pytest.param("", id="пусто"),
    pytest.param(" ", id="пробел"),
    pytest.param("AB", id="две-буквы"),
    pytest.param("a", id="буква"),
    pytest.param("5", id="цифра-без-keycap"),
    pytest.param("\U0001f680\U0001f680", id="два-эмодзи"),
    pytest.param("\U0001f680 ", id="эмодзи-и-пробел"),
    pytest.param("a\U0001f680", id="буква-и-эмодзи"),
    pytest.param("\U0001f1f7", id="одиночный-regional-indicator"),
    pytest.param("\U0001f3fb", id="одиночный-тон-кожи"),
    pytest.param("‍", id="голый-ZWJ"),
    pytest.param("<img src=x onerror=alert(1)>", id="html"),
    pytest.param("&#128640;", id="html-entity"),
    pytest.param("\U0001f680<script>", id="эмодзи-и-скрипт"),
]


@pytest.mark.parametrize("value", ACCEPTED)
def test_accepts_single_emoji(value: str) -> None:
    assert ProjectBadgeUpdate(emoji=value).emoji == value


@pytest.mark.parametrize("value", REJECTED)
def test_rejects_text_and_multiple_clusters(value: str) -> None:
    with pytest.raises(ValidationError):
        ProjectBadgeUpdate(emoji=value)


def test_rejects_trailing_newline() -> None:
    """Регресс на `\\A…\\Z`: `$` в Python матчится и ПЕРЕД завершающим \\n."""
    with pytest.raises(ValidationError):
        ProjectBadgeUpdate(emoji="\U0001f680\n")


def test_rejects_chain_longer_than_column() -> None:
    """Двадцать пиктографов через ZWJ — 39 кодпоинтов.

    Форму проходит, в VARCHAR(32) не влезает. Без проверки длины ДО регулярки
    это Postgres 22001, то есть 500 вместо 422.
    """
    chain = "‍".join("\U0001f680" for _ in range(20))
    assert len(chain) > 32
    with pytest.raises(ValidationError):
        ProjectBadgeUpdate(emoji=chain)


def test_none_clears_badge() -> None:
    assert ProjectBadgeUpdate(emoji=None).emoji is None


def test_emoji_key_is_required() -> None:
    """«Забыл прислать» не равно «сними» — дефолта у поля нет."""
    with pytest.raises(ValidationError):
        ProjectBadgeUpdate()


def test_extra_key_forbidden() -> None:
    with pytest.raises(ValidationError):
        ProjectBadgeUpdate(emoji=None, colour="red")
