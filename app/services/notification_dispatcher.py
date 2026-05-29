"""Dispatch domain events into per-user notifications + push.

Каждый вызов = ОДИН recipient (фан-аут делается на стороне caller'а через
loop по списку watcher'ов/mentioned_ids/assignee). Это упрощает учёт
`notification_preferences`: dispatch() читает prefs один раз и решает
независимо по in-app и push каналам (см. `app.services.notification_prefs`).

Flow внутри `dispatch()`:
    1. Загрузить prefs (normalized).
    2. Если оба канала off → silent skip.
    3. Если `prefs[kind].in_app` — INSERT в `notifications` (in-app Inbox).
    4. После `session.commit()` (caller'ом), если `prefs[kind].push` —
       `send_to_employee()` через asyncio.create_task.

Поскольку `send_to_employee` сам коммитит свою transaction (удаление 410/404
подписок), вызывать его НУЖНО ПОСЛЕ commit'а основной транзакции caller'а,
иначе SQLAlchemy session конфликтует.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory, tenant_scoped_session
from app.models.notification import Notification, NotificationPreferences
from app.services.notification_prefs import (
    KindPref,
    normalize_prefs,
    should_send_inapp,
    should_send_push,
)
from app.services.push_sender import send_to_employee

log = structlog.get_logger("notification_dispatcher")


async def _load_prefs(
    session: AsyncSession, *, employee_id: UUID
) -> dict[str, KindPref]:
    row = await session.execute(
        select(NotificationPreferences.prefs).where(
            NotificationPreferences.employee_id == employee_id
        )
    )
    raw = row.scalar_one_or_none()
    return normalize_prefs(raw)


async def queue_notification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    employee_id: UUID,
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    """Insert in-app notification row WITHOUT checking preferences.

    Doesn't commit — caller controls the transaction. Doesn't send push.
    Use `dispatch()` for the high-level path (prefs-aware in-app + push).
    """
    notification = Notification(
        tenant_id=tenant_id,
        employee_id=employee_id,
        kind=kind,
        title=title,
        body=body,
        url=url,
        payload=payload,
    )
    session.add(notification)
    return notification


def schedule_push(
    *,
    tenant_id: UUID,
    employee_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Schedule a background push delivery (no prefs check — caller decided).

    Runs in a brand-new tenant-scoped session (since the caller's session
    may already be closed by the time the task runs). Errors are logged
    but not propagated — the in-app notification is already persisted.
    """

    async def _runner() -> None:
        try:
            async with tenant_scoped_session(tenant_id) as bg_session:
                await send_to_employee(
                    bg_session, employee_id=employee_id, payload=payload
                )
        except Exception as e:  # noqa: BLE001 — best-effort background task
            log.warning(
                "push.background_failed",
                employee_id=str(employee_id),
                err=str(e),
            )

    task = asyncio.create_task(_runner())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


_pending_tasks: set[asyncio.Task] = set()


async def dispatch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    employee_id: UUID,
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Queue in-app + schedule push, respecting per-channel preferences.

    Both channels default to enabled; a kind is silenced fully only when
    the user explicitly turned BOTH `in_app` and `push` off.
    """
    prefs = await _load_prefs(session, employee_id=employee_id)
    wants_inapp = should_send_inapp(prefs, kind)
    wants_push = should_send_push(prefs, kind)
    if not wants_inapp and not wants_push:
        return

    if wants_inapp:
        await queue_notification(
            session,
            tenant_id=tenant_id,
            employee_id=employee_id,
            kind=kind,
            title=title,
            body=body,
            url=url,
            payload=payload,
        )

    if wants_push:
        schedule_push(
            tenant_id=tenant_id,
            employee_id=employee_id,
            payload={
                "title": title,
                "body": body,
                "url": url,
                "kind": kind,
            },
        )


# Re-export for tests / explicit usage.
_ = get_session_factory
