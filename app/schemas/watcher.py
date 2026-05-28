"""Pydantic schemas for task watchers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

WatcherReason = Literal["assignee", "creator", "mentioned", "manual"]


class WatcherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    added_reason: WatcherReason
    added_at: datetime
    email: str | None = None
    full_name: str | None = None
