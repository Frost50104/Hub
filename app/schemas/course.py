"""Pydantic-схемы курсов/уроков (Ф3a)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название не может быть пустым")
    return v


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    course_type: str = Field(default="info", pattern="^(mandatory|recommended|career|info)$")
    progression_mode: str = Field(default="sequential", pattern="^(sequential|free|mixed)$")

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    course_type: str | None = Field(default=None, pattern="^(mandatory|recommended|career|info)$")
    progression_mode: str | None = Field(default=None, pattern="^(sequential|free|mixed)$")
    certificate_enabled: bool | None = None


class LessonMeta(BaseModel):
    """Урок в списке курса — без контента."""

    id: UUID
    title: str
    position: int
    content_format: str
    unlock_rule: str
    status: str
    locked: bool = False
    completed: bool = False
    started: bool = False


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audience_id: UUID | None
    title: str
    description: str | None
    course_type: str
    progression_mode: str
    certificate_enabled: bool = False
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Персональное (заполняется в API):
    lessons_total: int = 0
    lessons_completed: int = 0
    enrolled: bool = False
    due_at: datetime | None = None
    completed: bool = False


class CourseListResponse(BaseModel):
    items: list[CourseResponse]
    content_role: str


class CourseDetailResponse(CourseResponse):
    lessons: list[LessonMeta] = []


class LessonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content_format: str = Field(default="blocks", pattern="^(blocks|pdf)$")

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class LessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: dict[str, Any] | None = None
    content_format: str | None = Field(default=None, pattern="^(blocks|pdf)$")
    pdf_media_id: UUID | None = None
    forbid_download: bool | None = None
    unlock_rule: str | None = Field(default=None, pattern="^(inherit|free|after_prev_test)$")
    status: str | None = Field(default=None, pattern="^(draft|published)$")


class LessonContentResponse(BaseModel):
    id: UUID
    course_id: UUID
    title: str
    position: int
    content_format: str
    content: dict[str, Any] | None
    pdf_url: str | None = None
    forbid_download: bool = False
    unlock_rule: str
    status: str
    completed: bool = False
    # Ответы на checkQuestion + карта досмотра видео (для восстановления UI).
    block_state: dict[str, Any] = {}
    # Гейты завершения (фронт показывает, чего не хватает).
    gate_blocks: list[str] = []
    required_videos: list[str] = []
    # Навигация.
    prev_lesson_id: UUID | None = None
    next_lesson_id: UUID | None = None
    next_locked: bool = False


class ReorderBody(BaseModel):
    lesson_ids: list[UUID] = Field(min_length=1, max_length=200)


class AssignBody(BaseModel):
    profile_ids: list[UUID] = Field(min_length=1, max_length=1000)
    due_at: datetime | None = None


class BlockAnswerBody(BaseModel):
    answer: int = Field(ge=0, le=20)


class VideoProgressBody(BaseModel):
    media_id: UUID
    intervals: list[list[float]] = Field(max_length=200)
    duration: float = Field(gt=0, le=24 * 3600)


class TemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: dict[str, Any]

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content: dict[str, Any]
    created_at: datetime
