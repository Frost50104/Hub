"""Send a Web Push to one employee's subscriptions via pywebpush.

Subscriptions returning 404/410 from the push transport are deleted from
`push_subscriptions` (standard sanitization — the browser dropped them).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.push_subscription import PushSubscription

log = structlog.get_logger("push_sender")

_DEAD_STATUSES = {404, 410}
_vapid_private_pem_cache: str | None = None


def _load_vapid_private_key() -> str | None:
    """Read the VAPID private PEM from disk once and cache the value."""
    global _vapid_private_pem_cache
    if _vapid_private_pem_cache is not None:
        return _vapid_private_pem_cache
    settings = get_settings()
    path = settings.vapid_private_key_path
    if path is None:
        return None
    try:
        _vapid_private_pem_cache = Path(path).read_text()
    except OSError as e:
        log.warning("vapid.read_failed", path=str(path), err=str(e))
        return None
    return _vapid_private_pem_cache


def _send_blocking(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, Any],
    vapid_private_pem: str,
    vapid_subject: str,
) -> int:
    """Returns HTTP status from the push transport. Raises on transport errors."""
    response = webpush(
        subscription_info={
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        },
        data=json.dumps(payload),
        vapid_private_key=vapid_private_pem,
        vapid_claims={"sub": vapid_subject},
    )
    return int(getattr(response, "status_code", 0))


async def send_to_employee(
    session: AsyncSession,
    *,
    employee_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Fan-out push to every subscription this employee has, in parallel.

    Updates `last_seen_at` on success; deletes the row on 404/410.
    Silent no-op if VAPID isn't configured (no key file / no subject) —
    in-app notification still works via dispatcher's INSERT.
    """
    settings = get_settings()
    vapid_pem = _load_vapid_private_key()
    if vapid_pem is None or not settings.vapid_subject:
        log.debug("push.skip_no_vapid", employee_id=str(employee_id))
        return

    subs = (
        await session.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
            ).where(PushSubscription.employee_id == employee_id)
        )
    ).all()
    if not subs:
        return

    async def _one(row: Any) -> tuple[int, int]:
        try:
            status = await asyncio.to_thread(
                _send_blocking,
                endpoint=row.endpoint,
                p256dh=row.p256dh,
                auth=row.auth,
                payload=payload,
                vapid_private_pem=vapid_pem,
                vapid_subject=settings.vapid_subject,
            )
            return row.id, status
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else 0
            log.warning(
                "push.webpush_error",
                sub_id=row.id,
                status=status,
                err=str(e),
            )
            return row.id, status
        except Exception as e:  # noqa: BLE001 — transport/network failure
            log.warning("push.send_failed", sub_id=row.id, err=str(e))
            return row.id, 0

    results = await asyncio.gather(*(_one(s) for s in subs))
    dead_ids = [sub_id for sub_id, status in results if status in _DEAD_STATUSES]
    alive_ids = [
        sub_id
        for sub_id, status in results
        if 200 <= status < 300 and sub_id not in dead_ids
    ]
    if dead_ids:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.id.in_(dead_ids))
        )
    if alive_ids:
        await session.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(alive_ids))
            .values(last_seen_at=__import__("sqlalchemy").text("now()"))  # noqa
        )
    await session.commit()
