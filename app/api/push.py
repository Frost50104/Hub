"""Push subscription endpoints.

`subscribe` зовётся не единожды: тихая переподписка при каждом запуске PWA
(`web/src/lib/pushRefresh.ts`) шлёт её снова, и каждый такой вызов ПРОДЛЕВАЕТ
`last_seen_at`. На этом держится гейт свежести в `push_sender`: подписка живёт
ровно столько, сколько её подтверждают запуском приложения. Пара «гейт +
продление» неразделима — гейт без продления просто выключает пуши.

Повторная подписка тем же endpoint'ом идемпотентна (UPSERT).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth_any
from app.models.push_subscription import PushSubscription
from app.schemas.notification import PushSubscribeBody
from app.services.push_sender import describe_push_result, send_to_employee

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
            last_seen_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                # employee_id перезаписывается намеренно: один браузер — одна
                # подписка на origin, и после смены пользователя endpoint тот же.
                "employee_id": principal.employee_id,
                "p256dh": body.keys.p256dh,
                "auth": body.keys.auth,
                "user_agent": body.user_agent,
                "last_seen_at": func.now(),
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


class PushTestResponse(BaseModel):
    """Итог самопроверки — словами, которые можно показать человеку."""

    ok: bool
    subscriptions: int
    sent: int
    removed: int
    stale: int
    detail: str


@router.post("/push/test", response_model=PushTestResponse)
async def send_test_push(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> PushTestResponse:
    """Отправить пуш самому себе и честно сказать, что получилось.

    До этой ручки убедиться в доставке можно было только чтением журнала на
    сервере — то есть никому, кроме разработчика. Пуш — часть продукта, у
    которой не было ни одного способа проверки изнутри продукта.
    """
    await enforce_rate_limit(
        bucket="push:test",
        employee_id=str(principal.employee_id),
        limit=10,
        window_sec=3600,
    )
    result = await send_to_employee(
        db,
        employee_id=principal.employee_id,
        payload={
            "title": "Проверка уведомлений",
            "body": "Если вы видите это сообщение — уведомления работают.",
            "url": "/settings/notifications",
            "kind": "push.test",
        },
    )
    return PushTestResponse(
        ok=result.sent > 0,
        subscriptions=result.subscriptions,
        sent=result.sent,
        removed=result.removed,
        stale=result.skipped_stale,
        detail=describe_push_result(result),
    )
