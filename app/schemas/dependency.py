"""Schemas for task dependencies (Phase 4.3)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaskDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    predecessor_id: UUID
    successor_id: UUID
    created_at: datetime
