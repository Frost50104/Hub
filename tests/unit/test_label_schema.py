"""Валидация схем labels: trim имени, hex-цвет."""

import pytest
from pydantic import ValidationError

from app.schemas.label import LabelCreate, LabelUpdate


def test_name_is_stripped():
    assert LabelCreate(name="  Баг  ").name == "Баг"


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        LabelCreate(name="   ")


def test_name_too_long_rejected():
    with pytest.raises(ValidationError):
        LabelCreate(name="x" * 65)


def test_color_default():
    assert LabelCreate(name="Баг").color == "#FFB200"


@pytest.mark.parametrize("color", ["#ffb200", "#FFB200", "#00aA99"])
def test_valid_colors(color):
    assert LabelCreate(name="x", color=color).color == color


@pytest.mark.parametrize("color", ["red", "#FFF", "#GGGGGG", "FFB200", "#FFB20000"])
def test_invalid_colors_rejected(color):
    with pytest.raises(ValidationError):
        LabelCreate(name="x", color=color)


def test_update_all_fields_optional():
    body = LabelUpdate()
    assert body.name is None and body.color is None


def test_update_validates_color():
    with pytest.raises(ValidationError):
        LabelUpdate(color="oops")
