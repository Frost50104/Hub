"""Журнал действий API (ТЗ §27) — чтение, только hub:admin."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.audit import AuditLog
from app.models.shadow import ShadowUser

router = APIRouter(tags=["learn-audit"])


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: UUID | None
    actor_name: str | None = None
    action: str
    object_type: str
    object_id: UUID | None
    object_label: str | None
    diff: dict[str, Any] | None
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int


@router.get("/learn/audit", response_model=AuditListResponse)
async def list_audit(
    object_type: str | None = Query(default=None, max_length=32),
    object_id: UUID | None = None,
    actor_id: UUID | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_auth(roles=["admin"])),
    db: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    stmt = select(AuditLog)
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id is not None:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if date_from is not None:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )

    actor_ids = {r.actor_id for r in rows if r.actor_id is not None}
    names: dict[UUID, str] = {}
    if actor_ids:
        names = {
            row[0]: row[1]
            for row in await db.execute(
                select(ShadowUser.employee_id, ShadowUser.full_name).where(
                    ShadowUser.employee_id.in_(actor_ids)
                )
            )
        }
    items = []
    for r in rows:
        entry = AuditEntryResponse.model_validate(r)
        entry.actor_name = names.get(r.actor_id) if r.actor_id else None
        items.append(entry)
    return AuditListResponse(items=items, total=total)
