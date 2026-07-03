"""Pydantic schemas for project labels (теги задач)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(default="#FFB200", pattern=COLOR_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class LabelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    color: str


class LabelAssignmentResponse(BaseModel):
    task_id: UUID
    label_id: UUID
