"""Pydantic schemas for custom-field definitions + per-task values (3.6.10)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CustomFieldType = Literal[
    "text",
    "number",
    "date",
    "select",
    "multi_select",
    "person",
    "checkbox",
]


class CustomFieldOption(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class CustomFieldDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: CustomFieldType
    # Mandatory for select/multi_select, ignored otherwise.
    options: list[CustomFieldOption] = Field(default_factory=list)


class CustomFieldDefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    options: list[CustomFieldOption] | None = None
    position: Decimal | None = None
    # NOTE: `type` is NOT editable — changing it would orphan existing values.
    # Workflow for type change: create new field, migrate values, delete old.


class CustomFieldDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    type: CustomFieldType
    options: list[CustomFieldOption]
    position: Decimal
    created_at: datetime


class CustomFieldValueSet(BaseModel):
    """PUT body for setting a single value. `value` shape depends on type."""

    value: Any


class CustomFieldValueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    field_id: UUID
    value: Any
    updated_at: datetime
