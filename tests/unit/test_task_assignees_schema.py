"""Разрешение нового и легаси-входа исполнителей (0034).

`resolve_assignee_ids` — единственное место, где решается, что клиент имел в
виду. Контракт: None — «не трогать», [] — «снять всех».
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.task import MAX_ASSIGNEES, TaskCreate, TaskUpdate, resolve_assignee_ids

A = uuid.uuid4()
B = uuid.uuid4()


def test_absent_both_means_do_not_touch():
    assert resolve_assignee_ids(TaskUpdate.model_validate({"title": "Тест"})) is None


def test_legacy_assignee_id_maps_to_single_element_list():
    body = TaskUpdate.model_validate({"assignee_id": str(A)})
    assert resolve_assignee_ids(body) == [A]


def test_explicit_null_assignee_id_clears():
    """Старый бандл шлёт assignee_id: null → снимаются ВСЕ (replace-семантика)."""
    body = TaskUpdate.model_validate({"assignee_id": None})
    assert resolve_assignee_ids(body) == []


def test_empty_list_clears():
    assert resolve_assignee_ids(TaskUpdate.model_validate({"assignee_ids": []})) == []


def test_null_list_clears():
    assert resolve_assignee_ids(TaskUpdate.model_validate({"assignee_ids": None})) == []


def test_assignee_ids_wins_over_legacy_assignee_id():
    """Оба поля шлёт только НОВЫЙ бандл — ради совместимости со старым бэком."""
    body = TaskUpdate.model_validate({"assignee_ids": [str(A), str(B)], "assignee_id": str(A)})
    assert resolve_assignee_ids(body) == [A, B]

    body = TaskUpdate.model_validate({"assignee_ids": [str(A), str(B)], "assignee_id": None})
    assert resolve_assignee_ids(body) == [A, B]


def test_duplicates_deduped_preserving_order():
    body = TaskUpdate.model_validate({"assignee_ids": [str(A), str(A), str(B)]})
    assert resolve_assignee_ids(body) == [A, B]


def test_create_body_supports_both_inputs():
    assert resolve_assignee_ids(
        TaskCreate.model_validate({"title": "Т", "assignee_ids": [str(A)]})
    ) == [A]
    assert resolve_assignee_ids(
        TaskCreate.model_validate({"title": "Т", "assignee_id": str(B)})
    ) == [B]
    assert resolve_assignee_ids(TaskCreate.model_validate({"title": "Т"})) is None


def test_over_max_assignees_raises_validation_error():
    too_many = [str(uuid.uuid4()) for _ in range(MAX_ASSIGNEES + 1)]
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"assignee_ids": too_many})
