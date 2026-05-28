"""In-app inbox + per-user preferences."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.notification import Notification, NotificationPreferences
from app.schemas.notification import (
    NotificationResponse,
    PreferencesResponse,
    PreferencesUpdate,
    UnreadCount,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    stmt = (
        select(Notification)
        .where(Notification.employee_id == principal.employee_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [NotificationResponse.model_validate(n) for n in rows]


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def unread_count(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> UnreadCount:
    row = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.employee_id == principal.employee_id,
            Notification.is_read.is_(False),
        )
    )
    return UnreadCount(count=int(row.scalar_one()))


@router.post(
    "/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT
)
async def mark_read(
    notification_id: int,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    n = await db.get(Notification, notification_id)
    if n is None or n.employee_id != principal.employee_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Уведомление не найдено"
        )
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now(UTC)
        await db.commit()


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.employee_id == principal.employee_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()


# ─── Preferences ────────────────────────────────────────────────────────────


@router.get("/notifications/preferences", response_model=PreferencesResponse)
async def get_preferences(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    row = await db.execute(
        select(NotificationPreferences.prefs).where(
            NotificationPreferences.employee_id == principal.employee_id
        )
    )
    prefs = row.scalar_one_or_none()
    return PreferencesResponse(prefs=prefs or {})


@router.put("/notifications/preferences", response_model=PreferencesResponse)
async def put_preferences(
    body: PreferencesUpdate,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    await db.execute(
        pg_insert(NotificationPreferences)
        .values(
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            prefs=body.prefs,
        )
        .on_conflict_do_update(
            index_elements=["employee_id"],
            set_={"prefs": body.prefs, "updated_at": datetime.now(UTC)},
        )
    )
    await db.commit()
    return PreferencesResponse(prefs=body.prefs)
