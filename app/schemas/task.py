"""Pydantic schemas for Task endpoints (Hub-MVP.3a)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["todo", "in_progress", "in_review", "done"]
TaskPriority = Literal["low", "medium", "high", "urgent"]


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
    assignee_id: UUID | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    section_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    position: Decimal | None = None
    # Pydantic v2 has trouble distinguishing "explicit null" from "absent" by
    # default. For section/assignee/due/description we want "explicit null"
    # = unset, "absent" = keep current. Endpoint layer treats `is None` as
    # "absent" — clients send `null` only when they really mean "clear it".
    # TODO Hub-MVP.3b: switch to Pydantic Optional + Unset sentinel if needed.


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
    assignee_id: UUID | None
    assignee: AssigneeBrief | None = None
    created_by: UUID
    due_at: datetime | None
    position: Decimal
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
