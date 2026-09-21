"""Потолок тела комментария задачи — 20 000 и один на всех (ОС 21.09).

Отчёт на 9 279 символов не уходил: схема держала 4 000 с MVP, а 422 приходил
списком ошибок, который фронт показывал как «Request failed with status code
422». Проверяем на уровне СХЕМЫ — лимит срабатывает при разборе тела, до
хендлера (тот же приём, что в `test_legacy_payloads.py`).

Отдельно сторожим зеркала ассистента: `CommentArgs.text` и `PlanPatch.text`
обязаны нести ТОТ ЖЕ потолок, иначе план соберётся, а исполнение упадёт.
"""

from __future__ import annotations

import pytest
from annotated_types import MaxLen
from pydantic import BaseModel, ValidationError

from app.schemas.comment import COMMENT_MAX_LENGTH, CommentCreate, CommentUpdate
from app.services.assistant.plans import PlanPatch
from app.services.assistant.tools import CommentArgs

REPORT_LEN = 9_279  # длина отчёта из ОС 21.09


def _max_len(model: type[BaseModel], field: str) -> int | None:
    for meta in model.model_fields[field].metadata:
        if isinstance(meta, MaxLen):
            return meta.max_length
    return None


def test_limit_is_twenty_thousand() -> None:
    assert COMMENT_MAX_LENGTH == 20_000


@pytest.mark.parametrize("schema", [CommentCreate, CommentUpdate])
def test_long_report_fits(schema: type[BaseModel]) -> None:
    assert len(schema(body="я" * REPORT_LEN).body) == REPORT_LEN
    assert len(schema(body="я" * COMMENT_MAX_LENGTH).body) == COMMENT_MAX_LENGTH


@pytest.mark.parametrize("schema", [CommentCreate, CommentUpdate])
def test_over_limit_rejected_as_string_too_long(schema: type[BaseModel]) -> None:
    with pytest.raises(ValidationError) as exc:
        schema(body="я" * (COMMENT_MAX_LENGTH + 1))
    err = exc.value.errors()[0]
    # Этот тип и `ctx.max_length` разбирает клиентский `extractErrorDetail`.
    assert err["type"] == "string_too_long"
    assert err["ctx"]["max_length"] == COMMENT_MAX_LENGTH


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (CommentCreate, "body"),
        (CommentUpdate, "body"),
        (CommentArgs, "text"),
        (PlanPatch, "text"),
    ],
)
def test_every_mirror_carries_the_same_ceiling(model: type[BaseModel], field: str) -> None:
    assert _max_len(model, field) == COMMENT_MAX_LENGTH
