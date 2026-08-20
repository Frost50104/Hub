"""Pydantic-схемы этапов проекта (редизайн, волна 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SystemStatus = Literal["todo", "in_progress", "in_review", "done"]


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    system_status: SystemStatus
    # None — в конец ленты.
    position: int | None = Field(default=None, ge=0)


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    system_status: SystemStatus | None = None
    position: int | None = Field(default=None, ge=0)


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    system_status: SystemStatus
    position: int
    created_at: datetime
    # Задач в этапе (неархивных, верхнего уровня) — для «N из M» в шапке
    # колонки. Заполняет ТОЛЬКО список этапов; одиночные ручки отдают None.
    task_count: int | None = None
