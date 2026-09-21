"""Схемы шаблонов проектов (0060). Тела запросов — `extra="forbid"`: лишний
ключ от клиента обязан быть 422, а не молчаливым no-op."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.project import ProjectResponse

_KEY = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_-]*$")


class TemplateCreate(BaseModel):
    """Шаблон с нуля."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    anchor_on: date | None = None


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_on: date


class SaveAsTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    anchor_on: date | None = None
    include_members: bool = True
    include_attachments: bool = True


class ProjectFromTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    key: str | None = _KEY
    start_on: date | None = None
    folder_id: UUID | None = None
    include_members: bool = True
    include_attachments: bool = True


class DroppedCounts(BaseModel):
    archived: int
    orphan_subtasks: int
    recurrence_steps: int


class DroppedPerson(BaseModel):
    employee_id: UUID
    name: str
    tasks: int


class CopyPreview(BaseModel):
    tasks: int
    subtasks: int
    too_big: bool
    max_tasks: int
    dropped: DroppedCounts
    dropped_people: list[DroppedPerson]
    attachments: int
    attachment_bytes: int
    members: int
    notify_people: int
    first_due: date | None
    last_due: date | None
    overdue_after_shift: int
    due_soon_reminders: int
    suggested_anchor_on: date
    # Только у предпросмотра создания проекта.
    shift_days: int = 0
    start_on: date | None = None
    disk_ok: bool = True


class CopyReportResponse(BaseModel):
    tasks: int
    subtasks: int
    dropped: DroppedCounts
    dropped_people: list[DroppedPerson]
    attachments_copied: int
    attachments_missing: int
    notified: int


class ProjectFromTemplateResponse(BaseModel):
    project: ProjectResponse
    report: CopyReportResponse


class TemplateListItem(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None
    badge_emoji: str | None
    badge_url: str | None
    template_anchor_on: date | None
    created_by: UUID
    author_name: str | None
    author_deleted: bool
    task_count: int
    attachment_count: int
    attachment_bytes: int
    member_count: int
    use_count: int
    can_edit: bool
    updated_at: datetime


class TemplateSettings(BaseModel):
    enabled: bool
    env_enabled: bool


class TemplateSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
