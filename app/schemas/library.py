"""Pydantic-схемы библиотеки знаний (Ф1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.org import AudienceRuleBody


def _strip_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название не может быть пустым")
    return v


class AudienceBody(BaseModel):
    is_all: bool = True
    rules: list[AudienceRuleBody] = Field(default_factory=list, max_length=50)


# --- Разделы -----------------------------------------------------------------


class SectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class SectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_title(v)


class SectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    title: str
    position: int
    audience_id: UUID | None


# --- Материалы ---------------------------------------------------------------

# Внешние ссылки: только безопасные протоколы (adversarial-ревью §10).
URL_PATTERN = r"^https?://\S+$"


class MaterialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    kind: str = Field(pattern="^(file|link)$")
    url: str | None = Field(default=None, pattern=URL_PATTERN, max_length=2000)
    section_id: UUID | None = None
    requires_acknowledgement: bool = False
    re_ack_on_new_version: bool = False
    ack_deadline_days: int | None = Field(default=None, ge=1, le=365)
    review_period_months: int | None = Field(default=None, ge=1, le=60)
    owner_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class MaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    url: str | None = Field(default=None, pattern=URL_PATTERN, max_length=2000)
    section_id: UUID | None = None
    requires_acknowledgement: bool | None = None
    re_ack_on_new_version: bool | None = None
    ack_deadline_days: int | None = Field(default=None, ge=1, le=365)
    review_period_months: int | None = Field(default=None, ge=1, le=60)
    owner_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_title(v)


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    file_name: str
    mime: str
    size_bytes: int
    note: str | None
    created_at: datetime


class StatusBody(BaseModel):
    status: str = Field(pattern="^(draft|review|published|archived)$")


class AckBody(BaseModel):
    version_no: int = Field(ge=0)


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    section_id: UUID | None
    audience_id: UUID | None
    title: str
    description: str | None
    kind: str
    url: str | None
    current_version_no: int | None
    requires_acknowledgement: bool
    re_ack_on_new_version: bool
    ack_deadline_days: int | None
    status: str
    owner_id: UUID | None
    owner_name: str | None = None
    published_at: datetime | None
    review_period_months: int | None
    next_review_at: datetime | None
    updated_at: datetime
    # Персональные флаги текущего пользователя (заполняются в API):
    current_version: VersionResponse | None = None
    opened_by_me: bool = False
    acked_by_me: bool = False
    ack_pending: bool = False  # обязателен и мной ещё не подтверждён


class LibraryResponse(BaseModel):
    sections: list[SectionResponse]
    materials: list[MaterialResponse]
    # Контент-роль текущего пользователя — UI решает, показывать ли управление.
    content_role: str


class AckReportRow(BaseModel):
    profile_id: UUID
    full_name: str
    store_id: UUID | None
    granted_at: datetime | None
    opened_at: datetime | None
    acknowledged_at: datetime | None
    deadline_at: datetime | None
    overdue: bool


class AckReportResponse(BaseModel):
    material_id: UUID
    total: int
    acked: int
    rows: list[AckReportRow]
