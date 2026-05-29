"""Unit tests for `app.services.custom_field_validator`.

Pure / sync — no DB. Verifies the seven primitive types coerce/raise as
documented in the module docstring.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.custom_field import CustomFieldDefinition
from app.services.custom_field_validator import (
    CustomFieldValueError,
    validate,
)


def _def(type_: str, *, options: list[dict] | None = None) -> CustomFieldDefinition:
    return CustomFieldDefinition(
        id=uuid4(),
        tenant_id=uuid4(),
        project_id=uuid4(),
        name="x",
        type=type_,
        options=options or [],
        position=1,
    )


def test_text_passes_and_rejects_oversize() -> None:
    assert validate(_def("text"), "hello") == "hello"
    with pytest.raises(CustomFieldValueError):
        validate(_def("text"), "x" * 2001)
    with pytest.raises(CustomFieldValueError):
        validate(_def("text"), 42)


def test_number_coerces_string_and_rejects_nan() -> None:
    assert validate(_def("number"), 3) == 3.0
    assert validate(_def("number"), "1.5") == 1.5
    with pytest.raises(CustomFieldValueError):
        validate(_def("number"), "не число")
    with pytest.raises(CustomFieldValueError):
        validate(_def("number"), float("nan"))
    with pytest.raises(CustomFieldValueError):
        validate(_def("number"), True)  # bool is not a number


def test_date_iso_only() -> None:
    assert validate(_def("date"), "2026-05-29") == "2026-05-29"
    with pytest.raises(CustomFieldValueError):
        validate(_def("date"), "29.05.2026")
    with pytest.raises(CustomFieldValueError):
        validate(_def("date"), 20260529)


def test_select_rejects_unknown_option() -> None:
    d = _def(
        "select", options=[{"id": "lo", "label": "Low"}, {"id": "hi", "label": "Hi"}]
    )
    assert validate(d, "lo") == "lo"
    with pytest.raises(CustomFieldValueError):
        validate(d, "mid")


def test_multi_select_dedupes_and_validates_each() -> None:
    d = _def(
        "multi_select",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    )
    assert validate(d, ["a", "b", "a"]) == ["a", "b"]
    assert validate(d, []) == []
    assert validate(d, None) == []
    with pytest.raises(CustomFieldValueError):
        validate(d, ["a", "c"])
    with pytest.raises(CustomFieldValueError):
        validate(d, "a")  # not a list


def test_person_validates_uuid() -> None:
    uid = str(uuid4())
    assert validate(_def("person"), uid) == uid
    with pytest.raises(CustomFieldValueError):
        validate(_def("person"), "not-a-uuid")


def test_checkbox_strict_bool() -> None:
    assert validate(_def("checkbox"), True) is True
    assert validate(_def("checkbox"), False) is False
    assert validate(_def("checkbox"), None) is False  # absent → off
    with pytest.raises(CustomFieldValueError):
        validate(_def("checkbox"), "yes")


def test_null_clears_value_for_nullable_types() -> None:
    assert validate(_def("text"), None) is None
    assert validate(_def("number"), None) is None
    assert validate(_def("date"), None) is None
    assert validate(_def("select", options=[{"id": "a", "label": "A"}]), None) is None
    assert validate(_def("person"), None) is None


def test_unknown_type_raises() -> None:
    bogus = _def("text")
    bogus.type = "wormhole"
    with pytest.raises(CustomFieldValueError):
        validate(bogus, "x")
