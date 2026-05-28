"""Push subscription endpoints — clients call `subscribe` once after
`Notification.requestPermission()` + `pushManager.subscribe(...)`.
Re-subscribing with the same endpoint is idempotent (UPSERT)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from signaris_auth import Principal
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.push_subscription import PushSubscription
from app.schemas.notification import PushSubscribeBody

router = APIRouter(tags=["push"])


@router.post("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: PushSubscribeBody,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        pg_insert(PushSubscription)
        .values(
            tenant_id=principal.tenant_id,
            employee_id=principal.employee_id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=body.user_agent,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "employee_id": principal.employee_id,
                "p256dh": body.keys.p256dh,
                "auth": body.keys.auth,
                "user_agent": body.user_agent,
            },
        )
    )
    await db.commit()


@router.delete("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    endpoint: str = Query(..., min_length=20, max_length=2048),
    _principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    await db.commit()
