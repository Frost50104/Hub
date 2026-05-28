"""Pydantic schemas for task activity feed."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: UUID
    actor_id: UUID
    kind: str
    payload: dict[str, Any] | None
    created_at: datetime
    # Enriched
    actor_email: str | None = None
    actor_full_name: str | None = None
