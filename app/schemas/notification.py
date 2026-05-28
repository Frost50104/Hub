"""Pydantic schemas for notifications + push subscriptions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ─── Push subscription ──────────────────────────────────────────────────────


class PushKeys(BaseModel):
    """The `keys` object emitted by `pushManager.subscribe(...)` in the browser."""

    p256dh: str
    auth: str


class PushSubscribeBody(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=256)


# ─── Notifications ──────────────────────────────────────────────────────────


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body: str
    url: str | None
    payload: dict[str, Any] | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


# ─── Preferences ────────────────────────────────────────────────────────────


class PreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prefs: dict[str, Any]


class PreferencesUpdate(BaseModel):
    prefs: dict[str, Any]
