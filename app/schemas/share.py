"""Pydantic schemas for share-management API + public payload (3.6.12)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShareCreate(BaseModel):
    expires_at: datetime | None = None


class ShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: Literal["task", "project"]
    entity_id: UUID
    token: UUID
    url: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


# ─── Public payload (returned by /api/public/{token}) ───────────────────────


class PublicTaskHit(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str
    due_at: datetime | None
    assignee_initials: str | None
    has_attachments: bool
    is_subtask: bool = False


class PublicSection(BaseModel):
    id: UUID
    name: str
    tasks: list[PublicTaskHit]


class PublicProjectComment(BaseModel):
    """Latest comments across all tasks in a public project — short context."""

    task_title: str
    author_initials: str | None
    body: str
    created_at: datetime


class PublicProjectView(BaseModel):
    kind: Literal["project"] = "project"
    name: str
    description: str | None
    sections: list[PublicSection]
    recent_comments: list[PublicProjectComment] = []


class PublicComment(BaseModel):
    author_initials: str | None
    body: str
    created_at: datetime


class PublicAttachmentMeta(BaseModel):
    filename: str
    size_bytes: int
    mime: str


class PublicTaskView(BaseModel):
    kind: Literal["task"] = "task"
    title: str
    description: str | None
    status: str
    priority: str
    start_at: datetime | None
    due_at: datetime | None
    assignee_initials: str | None
    created_by_initials: str | None
    created_at: datetime
    comments: list[PublicComment]
    attachments: list[PublicAttachmentMeta]
