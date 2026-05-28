"""Dispatch domain events into per-user notifications + push.

Каждый вызов = ОДИН recipient (фан-аут делается на стороне caller'а через
loop по списку watcher'ов/mentioned_ids/assignee). Это упрощает учёт
`notification_preferences` (если юзер отключил kind — pass), и оставляет
управление транзакцией caller'у.

Flow:
    1. Если `prefs[kind] == False` → silent skip.
    2. INSERT в `notifications` (in-app Inbox).
    3. После `session.commit()` — `send_to_employee()` через asyncio.create_task.

Поскольку `send_to_employee` сам коммитит свою transaction (удаление 410/404
подписок), вызывать его НУЖНО ПОСЛЕ commit'а основной транзакции caller'а,
иначе SQLAlchemy session конфликтует. Чтобы упростить — dispatcher
возвращает coroutine для пост-commit обработки.
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
from app.services.push_sender import send_to_employee

log = structlog.get_logger("notification_dispatcher")


async def _is_kind_enabled(
    session: AsyncSession, *, employee_id: UUID, kind: str
) -> bool:
    row = await session.execute(
        select(NotificationPreferences.prefs).where(
            NotificationPreferences.employee_id == employee_id
        )
    )
    prefs = row.scalar_one_or_none() or {}
    # Default: every kind enabled. Only explicit `False` disables.
    return prefs.get(kind, True) is not False


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
) -> Notification | None:
    """Insert in-app notification row.  Returns the row (or None if user opted out).

    Doesn't commit — caller controls the transaction. Doesn't send push.
    Use `flush_push()` after the surrounding commit to deliver pushes.
    """
    if not await _is_kind_enabled(session, employee_id=employee_id, kind=kind):
        return None
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
    """Schedule a background push delivery.

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

    # Fire-and-forget. We don't want to hold up the HTTP response on transport latency.
    task = asyncio.create_task(_runner())
    # Keep a strong ref so the GC doesn't eat the task before it runs.
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


_pending_tasks: set[asyncio.Task] = set()


# Convenience wrapper for callers that need both in-app + push together.
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
    """Queue in-app and schedule push. Caller still needs to `commit()`."""
    n = await queue_notification(
        session,
        tenant_id=tenant_id,
        employee_id=employee_id,
        kind=kind,
        title=title,
        body=body,
        url=url,
        payload=payload,
    )
    if n is None:
        return
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


# Re-export for tests / explicit usage. Marked `noqa` to keep lint happy.
_ = get_session_factory
