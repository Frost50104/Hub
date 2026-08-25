"""Лишние поля в теле = 422, а не тихий no-op (0045).

Колонок `tasks.status` и `project_stages.system_status` больше нет, вместе с
ними ушли именованные ловушки в схемах. Защиту держит `extra="forbid"`: старый
бандл (живёт до клика «Обновить» — `registerType: 'prompt'`) шлёт `status` в
PATCH задачи и `system_status` в PATCH колонки, и молчаливое игнорирование
показало бы ему «задача закрыта» при незакрытой задаче в базе.

Проверяем на уровне СХЕМЫ: HTTP-клиента в сьюте нет, все тесты зовут хендлеры
напрямую — а `extra="forbid"` срабатывает как раз при разборе тела, до
хендлера. Запрет на схеме = гарантированный 422 на границе FastAPI.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import STALE_PAYLOAD_DETAIL, validation_error_handler
from app.schemas.stage import StageCreate, StageUpdate
from app.schemas.task import TaskCreate, TaskUpdate


class TestLegacyFieldsRejected:
    def test_task_status_in_body(self):
        with pytest.raises(ValidationError):
            TaskCreate(title="Старый", status="done")
        with pytest.raises(ValidationError):
            TaskUpdate(status="done")

    def test_stage_system_status_in_body(self):
        with pytest.raises(ValidationError):
            StageCreate(name="Колонка", system_status="todo")
        with pytest.raises(ValidationError):
            StageUpdate(system_status="done")

    def test_any_unknown_field_not_just_legacy(self):
        # Ловушка теперь общая: опечатка в имени поля тоже ошибка, а не тихая
        # потеря значения.
        with pytest.raises(ValidationError):
            TaskUpdate(titel="Опечатка")

    def test_error_type_is_the_one_handler_looks_for(self):
        # Обработчик в app/main.py опознаёт случай по `type`; если pydantic
        # когда-нибудь переименует его, текст для человека молча исчезнет.
        with pytest.raises(ValidationError) as exc:
            TaskUpdate(status="done")
        assert any(e["type"] == "extra_forbidden" for e in exc.value.errors())


class TestFrontendBodyShapeStillValidates:
    """Оборотная сторона `extra="forbid"`: свой фронт обязан проходить.

    Наборы полей — дословно `TaskCreateBody`/`TaskUpdateBody` из
    `web/src/lib/tasks.ts` и `StageCreateBody`/`StageUpdateBody` из
    `web/src/lib/stages.ts`. Разъедутся — тест упадёт здесь, а не 422 у
    пользователя.
    """

    def test_task_create_full(self):
        body = TaskCreate(
            stage_id=uuid4(),
            title="Задача",
            description="Описание",
            section_id=uuid4(),
            parent_task_id=uuid4(),
            priority="high",
            assignee_id=uuid4(),
            assignee_ids=[uuid4()],
            start_at="2026-08-25T09:00:00Z",
            due_at="2026-08-26T09:00:00Z",
        )
        assert body.title == "Задача"

    def test_task_update_full(self):
        body = TaskUpdate(
            stage_id=uuid4(),
            title="Задача",
            description="Описание",
            section_id=None,
            done=True,
            priority="urgent",
            assignee_id=None,
            assignee_ids=[uuid4()],
            start_at=None,
            due_at=None,
            position=Decimal("1.5"),
        )
        assert body.done is True

    def test_stage_bodies(self):
        assert StageCreate(name="Идея", position=0).position == 0
        assert StageUpdate(name="Согласование").name == "Согласование"
        assert StageUpdate(position=2).position == 2


class TestValidationErrorHandler:
    async def _detail(self, errors: list[dict]) -> object:
        import json

        from fastapi.exceptions import RequestValidationError

        response = await validation_error_handler(None, RequestValidationError(errors))
        assert response.status_code == 422
        return json.loads(bytes(response.body))["detail"]

    async def test_extra_field_gets_human_text(self):
        # Без этой ветки фронт показал бы «Неизвестная ошибка»:
        # `extractErrorDetail` понимает только строковый detail.
        detail = await self._detail(
            [{"type": "extra_forbidden", "loc": ("body", "status"), "msg": "..."}]
        )
        assert detail == STALE_PAYLOAD_DETAIL

    async def test_ordinary_validation_keeps_default_shape(self):
        detail = await self._detail(
            [{"type": "string_too_short", "loc": ("body", "title"), "msg": "..."}]
        )
        assert isinstance(detail, list) and detail[0]["loc"] == ["body", "title"]

    async def test_unserializable_ctx_does_not_crash_the_handler(self):
        # В `ctx` попадают живые объекты исключений — без jsonable_encoder
        # обработчик сам падал бы в 500.
        detail = await self._detail(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "due_at"),
                    "msg": "...",
                    "ctx": {"error": ValueError("не дата")},
                }
            ]
        )
        assert isinstance(detail, list)
