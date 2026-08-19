"""Pydantic schemas for Task endpoints (Hub-MVP.3a)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["todo", "in_progress", "in_review", "done"]
TaskPriority = Literal["low", "medium", "high", "urgent"]

# Потолок фан-аута уведомлений (dispatch делает SELECT prefs + INSERT на
# получателя) и разумный предел для стека аватаров в UI. Живёт в схемах, а не
# в сервисе: сервис импортирует AssigneeBrief отсюда — обратный импорт дал бы
# цикл.
MAX_ASSIGNEES = 10


def dedupe(ids: Sequence[UUID]) -> list[UUID]:
    """Убрать дубли, сохранив порядок первого вхождения."""
    seen: set[UUID] = set()
    out: list[UUID] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class AssigneeBrief(BaseModel):
    """Minimal assignee info, enriched via shadow_users JOIN."""

    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    email: str | None
    full_name: str | None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    section_id: UUID | None = None
    parent_task_id: UUID | None = None
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    # DEPRECATED-вход: держим ради PWA-бандлов, которые живут днями после
    # деплоя (registerType: 'prompt'). Разрешение конфликта — resolve_assignee_ids.
    assignee_id: UUID | None = None
    assignee_ids: list[UUID] | None = Field(default=None, max_length=MAX_ASSIGNEES)
    start_at: datetime | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    section_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: UUID | None = None  # DEPRECATED-вход, см. TaskCreate
    assignee_ids: list[UUID] | None = Field(default=None, max_length=MAX_ASSIGNEES)
    start_at: datetime | None = None
    due_at: datetime | None = None
    position: Decimal | None = None
    # Для nullable-полей (section_id/assignee_id/start_at/due_at) endpoint
    # различает «поле не пришло» (нет в model_fields_set → не трогаем) и
    # «пришёл явный null» (очистить значение). Не-nullable поля (title/status/
    # priority/position) по-прежнему игнорируют null.


class TaskAssigneeAdd(BaseModel):
    """Тело POST /tasks/{id}/assignees — добавить одного исполнителя."""

    employee_id: UUID


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    section_id: UUID | None
    parent_task_id: UUID | None
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    # Источник истины для UI. Уволенные (shadow_users.deleted_at) сюда не
    # попадают, поэтому легаси-поля ниже с ним всегда согласованы — раньше
    # assignee_id мог быть непустым при assignee=null.
    assignees: list[AssigneeBrief] = []
    # DEPRECATED-выход: всегда выводится из assignees[0], а НЕ из ORM-атрибута —
    # поэтому удаление колонки в 0035 не потребует правок сериализации. Дефолт
    # None обязателен: без него model_validate(task) упадёт после 0035.
    assignee_id: UUID | None = None
    assignee: AssigneeBrief | None = None
    created_by: UUID
    start_at: datetime | None = None
    due_at: datetime | None
    position: Decimal
    # Номер в проекте («KEY-42» = project.key + seq). project_key заполняют
    # только кросс-проектные ручки (/me/tasks) — в контексте проекта фронт
    # берёт key из project-запроса.
    seq: int
    project_key: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
    # Счётчики строки контекста в списке. Заполняет ТОЛЬКО list_tasks (батчем,
    # см. services/task_counts.py); одиночные ручки отдают None — «не знаем».
    # Клиент обязан различать None (чип не рисуем) и 0 (знаем, что нет), иначе
    # чип мигал бы при каждом оптимистичном обновлении.
    comment_count: int | None = None
    attachment_count: int | None = None
    blocker_count: int | None = None


def resolve_assignee_ids(body: TaskCreate | TaskUpdate) -> list[UUID] | None:
    """Свести новый и легаси-вход к одному списку.

    Возврат: None — «исполнителей не трогать»; [] — «снять всех».

    `assignee_ids` побеждает при конфликте: прислать оба поля может только
    НОВЫЙ бандл, и делает он это ровно ради совместимости со старым бэкендом;
    жёсткая 422 сломала бы сценарий «новый фронт + откаченный бэк».
    """
    if "assignee_ids" in body.model_fields_set:
        return dedupe(body.assignee_ids or [])
    if "assignee_id" in body.model_fields_set:
        return [body.assignee_id] if body.assignee_id else []
    return None
