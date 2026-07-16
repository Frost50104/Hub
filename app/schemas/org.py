"""Pydantic-схемы оргструктуры + audience dry-run (Ф0 LMS)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_required(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название не может быть пустым")
    return v


class RefCreate(BaseModel):
    """Общая форма создания простого справочника (position/franchisee/group)."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)


class RefUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_required(v)


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=2000)
    franchisee_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=2000)
    franchisee_id: UUID | None = None
    archived: bool | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_required(v)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: UUID | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_required(v)


class GroupMembersReplace(BaseModel):
    member_ids: list[UUID] = Field(max_length=10_000)


class RefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    archived_at: datetime | None = None


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str | None
    address: str | None
    franchisee_id: UUID | None
    archived_at: datetime | None


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    parent_id: UUID | None


class GroupResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    member_ids: list[UUID]


class OrgSnapshotResponse(BaseModel):
    """Все справочники одним запросом — для админки и пикеров."""

    positions: list[RefResponse]
    position_groups: list[GroupResponse]
    stores: list[StoreResponse]
    store_groups: list[GroupResponse]
    franchisees: list[RefResponse]
    franchisee_groups: list[GroupResponse]
    departments: list[DepartmentResponse]
    user_groups: list[GroupResponse]


# --- Audience dry-run --------------------------------------------------------


class AudienceRuleBody(BaseModel):
    mode: str = Field(pattern="^(include|exclude)$")
    profile_ids: list[UUID] = Field(default_factory=list)
    position_ids: list[UUID] = Field(default_factory=list)
    position_group_ids: list[UUID] = Field(default_factory=list)
    store_ids: list[UUID] = Field(default_factory=list)
    store_group_ids: list[UUID] = Field(default_factory=list)
    franchisee_ids: list[UUID] = Field(default_factory=list)
    franchisee_group_ids: list[UUID] = Field(default_factory=list)
    department_ids: list[UUID] = Field(default_factory=list)
    user_group_ids: list[UUID] = Field(default_factory=list)


class AudienceDryRunBody(BaseModel):
    is_all: bool = False
    rules: list[AudienceRuleBody] = Field(default_factory=list, max_length=50)


class DryRunProfile(BaseModel):
    id: UUID
    full_name: str


class AudienceDryRunResponse(BaseModel):
    count: int
    sample: list[DryRunProfile]
