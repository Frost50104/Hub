"""Type-aware validation for custom-field values (3.6.10).

`validate(definition, raw)` returns a JSON-serialisable value ready for
JSONB storage, or raises `CustomFieldValueError` with a human-readable
Russian message that the API surfaces as HTTP 422.

The seven primitive types map to the following storage shapes:

| type          | input                       | stored value                |
|---------------|-----------------------------|-----------------------------|
| text          | str (≤ 2000 chars)          | str                         |
| number        | int | float | numeric-str   | float                       |
| date          | YYYY-MM-DD                  | str (ISO date)              |
| select        | option_id (str)             | str (option_id)             |
| multi_select  | [option_id, ...]            | list[str]                   |
| person        | shadow_users.employee_id    | str (UUID)                  |
| checkbox      | bool                        | bool                        |

Person-existence is verified against `shadow_users` by the API layer
(needs a session); this module stays pure / sync to keep the unit tests
trivial.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.models.custom_field import CustomFieldDefinition

_TEXT_MAX = 2000


class CustomFieldValueError(ValueError):
    """Raised when a value doesn't fit the definition's contract."""


def _opt_ids(definition: CustomFieldDefinition) -> set[str]:
    return {str(opt.get("id")) for opt in (definition.options or []) if "id" in opt}


def validate(definition: CustomFieldDefinition, raw: Any) -> Any:  # noqa: PLR0911
    """Coerce `raw` into the canonical JSON-serialisable shape, or raise."""
    t = definition.type

    if t == "text":
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise CustomFieldValueError("Текстовое поле требует строку")
        if len(raw) > _TEXT_MAX:
            raise CustomFieldValueError(
                f"Текст не должен превышать {_TEXT_MAX} символов"
            )
        return raw

    if t == "number":
        if raw is None:
            return None
        if isinstance(raw, bool):
            raise CustomFieldValueError("Числовое поле не принимает bool")
        try:
            value = float(raw)
        except (TypeError, ValueError) as e:
            raise CustomFieldValueError("Числовое поле требует число") from e
        # Reject NaN/Inf — Postgres JSONB accepts them but they break JSON spec.
        if value != value or value in (float("inf"), float("-inf")):
            raise CustomFieldValueError("Число должно быть конечным")
        return value

    if t == "date":
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise CustomFieldValueError("Дата должна быть строкой YYYY-MM-DD")
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError as e:
            raise CustomFieldValueError(
                "Дата должна быть в формате YYYY-MM-DD"
            ) from e

    if t == "select":
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise CustomFieldValueError("Выбор требует option id (строку)")
        if raw not in _opt_ids(definition):
            raise CustomFieldValueError(
                f"Опция {raw!r} не существует в этом поле"
            )
        return raw

    if t == "multi_select":
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise CustomFieldValueError("Мультивыбор требует список option id")
        opt_ids = _opt_ids(definition)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                raise CustomFieldValueError("Все option id должны быть строками")
            if item not in opt_ids:
                raise CustomFieldValueError(
                    f"Опция {item!r} не существует в этом поле"
                )
            if item in seen:
                continue
            seen.add(item)
            cleaned.append(item)
        return cleaned

    if t == "person":
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise CustomFieldValueError("Поле «человек» требует UUID")
        try:
            return str(UUID(raw))
        except ValueError as e:
            raise CustomFieldValueError("UUID невалиден") from e

    if t == "checkbox":
        if raw is None:
            return False
        if not isinstance(raw, bool):
            raise CustomFieldValueError("Чекбокс требует true/false")
        return raw

    raise CustomFieldValueError(f"Неизвестный тип поля: {t}")
