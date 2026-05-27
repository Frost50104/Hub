"""GET /api/me — authenticated identity + hub roles, used by SPA Welcome page.

This is the minimal endpoint Hub-MVP.1 needs to prove the SSO loop works:
unauthenticated → 401, authenticated → JSON principal with hub:* roles.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401 — declares dep order

from app.deps import get_db, require_auth

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    employee_id: UUID
    email: str
    full_name: str
    tenant_id: UUID
    tenant_slug: str
    hub_role: str | None


@router.get("/me", response_model=MeResponse)
async def get_me(
    principal: Principal = Depends(require_auth(roles=["admin", "member", "viewer"])),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    # The Depends(get_db) above runs shadow upsert; we don't need its session here.
    return MeResponse(
        employee_id=principal.employee_id,
        email=principal.email,
        full_name=principal.full_name,
        tenant_id=principal.tenant_id,
        tenant_slug=principal.tenant_slug,
        hub_role=principal.role_for("hub"),
    )
