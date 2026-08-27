"""Схемы проекта: лимит описания и строгость PATCH."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.project import DESCRIPTION_MAX, ProjectCreate, ProjectUpdate


def test_description_limit_is_the_same_in_create_and_update() -> None:
    """Асимметрия между create и update была бы беспричинной."""
    text = "я" * DESCRIPTION_MAX
    assert ProjectCreate(name="П", description=text).description == text
    assert ProjectUpdate(description=text).description == text


@pytest.mark.parametrize("model", [ProjectCreate, ProjectUpdate])
def test_description_over_limit_rejected(model: type) -> None:
    kwargs = {"description": "я" * (DESCRIPTION_MAX + 1)}
    if model is ProjectCreate:
        kwargs["name"] = "П"
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_update_forbids_extra_keys() -> None:
    """Иначе клиент получил бы 200 на запрос, который сервер не выполнил."""
    with pytest.raises(ValidationError):
        ProjectUpdate(name="П", badge_emoji="🚀")


def test_empty_string_clears_description() -> None:
    """Пустая строка — законное «стереть»; None означает «не трогай»."""
    assert ProjectUpdate(description="").description == ""
    assert ProjectUpdate(name="П").description is None
