"""Pydantic schemas for task comments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    author_id: UUID
    body: str
    mentioned_ids: list[UUID]
    edited_at: datetime | None
    created_at: datetime
    # Enriched via JOIN shadow_users.
    author_email: str | None = None
    author_full_name: str | None = None
