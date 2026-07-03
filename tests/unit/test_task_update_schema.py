"""TaskUpdate: разница «поле не пришло» vs «пришёл явный null».

PATCH-хендлер применяет nullable-поля только когда имя есть в
body.model_fields_set — эти тесты фиксируют контракт схемы, на который
он опирается.
"""

from app.schemas.task import TaskUpdate

NULLABLE_FIELDS = ("section_id", "assignee_id", "start_at", "due_at")


def test_absent_fields_not_in_fields_set():
    body = TaskUpdate.model_validate({"title": "x"})
    assert body.model_fields_set == {"title"}
    for field in NULLABLE_FIELDS:
        assert field not in body.model_fields_set
        assert getattr(body, field) is None


def test_explicit_null_lands_in_fields_set():
    payload = dict.fromkeys(NULLABLE_FIELDS)
    body = TaskUpdate.model_validate(payload)
    for field in NULLABLE_FIELDS:
        assert field in body.model_fields_set
        assert getattr(body, field) is None


def test_explicit_value_lands_in_fields_set():
    body = TaskUpdate.model_validate(
        {"assignee_id": "0b06df3e-7a1a-4a1b-9a56-1a4d1f7f9e00"}
    )
    assert "assignee_id" in body.model_fields_set
    assert body.assignee_id is not None


def test_empty_patch_has_empty_fields_set():
    body = TaskUpdate.model_validate({})
    assert body.model_fields_set == set()
