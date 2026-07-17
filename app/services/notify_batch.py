"""Батч-рассылка уведомлений (Ф2, adversarial-ревью §18/§31).

`dispatch()` хорош для одного получателя; «новость всем» на 200+ сотрудников
через цикл dispatch = 200 запросов prefs + 200 фоновых пуш-задач с
собственными сессиями → истощение connection-pool. Здесь:

- prefs всех получателей — ОДНИМ запросом;
- in-app строки — bulk add_all в сессию вызывающего (его транзакция);
- пуши — ОДНА фоновая задача на событие: свой tenant-scoped session,
  последовательная отправка (VAPID-endpoints переживают, пул — нет).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.notification import Notification, NotificationPreferences
from app.services.notification_prefs import (
    normalize_prefs,
    should_send_inapp,
    should_send_push,
)
from app.services.push_sender import send_to_employee

log = structlog.get_logger("notify_batch")

_pending_tasks: set[asyncio.Task] = set()


async def notify_many(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    employee_ids: list[UUID],
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """In-app bulk + одна фоновая пуш-задача. → сколько in-app создано."""
    if not employee_ids:
        return 0
    unique_ids = list(dict.fromkeys(employee_ids))

    prefs_rows = {
        row[0]: normalize_prefs(row[1])
        for row in await session.execute(
            select(
                NotificationPreferences.employee_id, NotificationPreferences.prefs
            ).where(NotificationPreferences.employee_id.in_(unique_ids))
        )
    }
    default_prefs = normalize_prefs(None)

    inapp_targets: list[UUID] = []
    push_targets: list[UUID] = []
    for emp_id in unique_ids:
        prefs = prefs_rows.get(emp_id, default_prefs)
        if should_send_inapp(prefs, kind):
            inapp_targets.append(emp_id)
        if should_send_push(prefs, kind):
            push_targets.append(emp_id)

    session.add_all(
        Notification(
            tenant_id=tenant_id,
            employee_id=emp_id,
            kind=kind,
            title=title,
            body=body,
            url=url,
            payload=payload,
        )
        for emp_id in inapp_targets
    )

    if push_targets:
        _schedule_push_batch(
            tenant_id=tenant_id,
            employee_ids=push_targets,
            payload={"title": title, "body": body, "url": url, "kind": kind},
        )
    log.info(
        "notify_batch.queued",
        kind=kind,
        inapp=len(inapp_targets),
        push=len(push_targets),
    )
    return len(inapp_targets)


def _schedule_push_batch(
    *, tenant_id: UUID, employee_ids: list[UUID], payload: dict[str, Any]
) -> None:
    async def _runner() -> None:
        try:
            async with tenant_scoped_session(tenant_id) as bg:
                for emp_id in employee_ids:
                    try:
                        await send_to_employee(bg, employee_id=emp_id, payload=payload)
                    except Exception as e:  # noqa: BLE001 — не роняем пачку
                        log.warning(
                            "notify_batch.push_failed",
                            employee_id=str(emp_id),
                            err=str(e),
                        )
        except Exception as e:  # noqa: BLE001
            log.warning("notify_batch.session_failed", err=str(e))

    task = asyncio.create_task(_runner())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
