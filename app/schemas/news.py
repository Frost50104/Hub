"""Pydantic-схемы новостей (Ф2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Заголовок не может быть пустым")
    return v


class NewsCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: dict[str, Any]  # TipTap {schema: 1, doc} — валидируется rich_content
    allow_comments: bool = True
    allow_reactions: bool = True
    requires_acknowledgement: bool = False

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_title(v)


class NewsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: dict[str, Any] | None = None
    allow_comments: bool | None = None
    allow_reactions: bool | None = None
    requires_acknowledgement: bool | None = None
    pinned_until: datetime | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else _strip_title(v)


class ReactionBody(BaseModel):
    emoji: str = Field(max_length=8)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Комментарий не может быть пустым")
        return v


class CommentResponse(BaseModel):
    id: UUID
    author_id: UUID
    author_name: str | None
    body: str
    edited_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime


class NewsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audience_id: UUID | None
    title: str
    body: dict[str, Any]
    allow_comments: bool
    allow_reactions: bool
    requires_acknowledgement: bool
    pinned_until: datetime | None
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    author_name: str | None = None
    # Персональное (заполняется в API):
    reactions: dict[str, int] = {}
    my_reactions: list[str] = []
    comments_count: int = 0
    acked_by_me: bool = False
    ack_pending: bool = False
    is_favorite: bool = False


class NewsListResponse(BaseModel):
    items: list[NewsResponse]
    total: int
    content_role: str
