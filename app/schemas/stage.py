"""Pydantic-схемы этапов проекта (редизайн, волна 2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # None — в конец ленты.
    position: int | None = Field(default=None, ge=0)
    # LEGACY-вход старых бандлов (0044): системного смысла у колонки больше
    # нет, поле принимаем явно и отвечаем 422.
    system_status: str | None = None


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    position: int | None = Field(default=None, ge=0)
    system_status: str | None = None


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    position: int
    created_at: datetime
    # Задач в этапе (неархивных, верхнего уровня) — для «N из M» в шапке
    # колонки. Заполняет ТОЛЬКО список этапов; одиночные ручки отдают None.
    task_count: int | None = None
