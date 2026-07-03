"""Tenant-wide endpoints: member autocomplete for @mentions etc.

`shadow_users` is RLS-scoped to the current tenant, so a raw SELECT (without
explicit `WHERE tenant_id = ...`) returns only the right set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.shadow import ShadowUser
from app.schemas.tenant import TenantMemberBrief

router = APIRouter(tags=["tenant"])


@router.get("/tenant/members", response_model=list[TenantMemberBrief])
async def list_tenant_members(
    q: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=10, ge=1, le=50),
    # Справочник сотрудников (email, ФИО) — только пользователям Hub,
    # а не любому валидному Signaris-JWT.
    _principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TenantMemberBrief]:
    stmt = (
        select(ShadowUser.employee_id, ShadowUser.email, ShadowUser.full_name)
        .where(ShadowUser.deleted_at.is_(None))
        .order_by(ShadowUser.full_name)
        .limit(limit)
    )
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(ShadowUser.email).like(pattern),
                func.lower(ShadowUser.full_name).like(pattern),
            )
        )
    rows = (await db.execute(stmt)).all()
    return [
        TenantMemberBrief(
            employee_id=r.employee_id,
            email=r.email,
            full_name=r.full_name,
            handle=r.email.split("@", 1)[0].lower(),
        )
        for r in rows
    ]
