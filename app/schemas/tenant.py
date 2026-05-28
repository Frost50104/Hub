"""Tenant-wide reference schemas (members for @mention autocomplete, etc.)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantMemberBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    email: str
    full_name: str
    # Local-part of email — convenience for client-side @mention rendering.
    handle: str
