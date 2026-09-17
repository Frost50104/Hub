"""Батч-рассылка уведомлений (Ф2, adversarial-ревью §18/§31).

`dispatch()` хорош для одного получателя; «новость всем» на 200+ сотрудников
через цикл dispatch = 200 запросов prefs + 200 фоновых пуш-задач с
собственными сессиями → истощение connection-pool. Здесь:

- prefs всех получателей — ОДНИМ запросом;
- in-app строки — bulk add_all в сессию вызывающего (его транзакция);
- пуши — ОДНА фоновая задача на событие: несколько tenant-scoped сессий
  (`PUSH_CONCURRENCY`), внутри каждой — последовательно; 200 получателей с
  мёртвыми endpoint'ами по 10 с таймаута иначе тянутся десятки минут.

Два порядка вызова:
- `notify_many()` — in-app строки в сессию вызывающего + пуш сразу; годится,
  когда откат транзакции ничего не сломает;
- `queue_many()` → commit → `schedule_push_batch()` — когда в той же
  транзакции ставятся метки дедупа (гонка: `started_notified_at`): пуш,
  ушедший ДО commit, при откате повторился бы через час всей сети.

Джобы (`asyncio.run`) обязаны в конце звать `drain()`: без него `asyncio.run`
отменяет незавершённые фоновые задачи, и хвост рассылки теряется молча.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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

# Параллельных сессий в одной пачке: пул процесса — 10, API рядом должен жить.
PUSH_CONCURRENCY = 4
DRAIN_TIMEOUT_SEC = 120.0


@dataclass(frozen=True)
class PushBatch:
    tenant_id: UUID
    employee_ids: list[UUID]
    payload: dict[str, Any]


async def queue_many(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    employee_ids: list[UUID],
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, PushBatch | None]:
    """In-app bulk в сессию вызывающего; пуш НЕ планирует — отдаёт пачку.

    → (сколько in-app создано, пачка для `schedule_push_batch` или None).
    """
    if not employee_ids:
        return 0, None
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

    log.info(
        "notify_batch.queued",
        kind=kind,
        inapp=len(inapp_targets),
        push=len(push_targets),
    )
    batch = (
        PushBatch(
            tenant_id=tenant_id,
            employee_ids=push_targets,
            payload={"title": title, "body": body, "url": url, "kind": kind},
        )
        if push_targets
        else None
    )
    return len(inapp_targets), batch


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
    created, batch = await queue_many(
        session,
        tenant_id=tenant_id,
        employee_ids=employee_ids,
        kind=kind,
        title=title,
        body=body,
        url=url,
        payload=payload,
    )
    if batch is not None:
        schedule_push_batch(batch)
    return created


def schedule_push_batch(batch: PushBatch) -> None:
    """Фоновая отправка пачки: звать ПОСЛЕ commit'а вызывающего."""
    if not batch.employee_ids:
        return
    lanes: list[list[UUID]] = [[] for _ in range(min(PUSH_CONCURRENCY, len(batch.employee_ids)))]
    for i, emp_id in enumerate(batch.employee_ids):
        lanes[i % len(lanes)].append(emp_id)

    async def _lane(ids: list[UUID]) -> None:
        try:
            async with tenant_scoped_session(batch.tenant_id) as bg:
                for emp_id in ids:
                    try:
                        await send_to_employee(bg, employee_id=emp_id, payload=batch.payload)
                    except Exception as e:  # noqa: BLE001 — не роняем пачку
                        log.warning(
                            "notify_batch.push_failed",
                            employee_id=str(emp_id),
                            err=str(e),
                        )
        except Exception as e:  # noqa: BLE001
            log.warning("notify_batch.session_failed", err=str(e))

    async def _runner() -> None:
        await asyncio.gather(*(_lane(ids) for ids in lanes))

    task = asyncio.create_task(_runner())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def drain(timeout_sec: float = DRAIN_TIMEOUT_SEC) -> int:
    """Дождаться фоновых пуш-задач (этого модуля и dispatcher'а) с потолком.

    → сколько задач НЕ уложилось и было отменено. Потолок обязателен:
    oneshot-джоба с часовым таймером не должна тянуться в следующий тик.
    """
    from app.services.notification_dispatcher import _pending_tasks as dispatcher_tasks

    pending = set(_pending_tasks) | set(dispatcher_tasks)
    if not pending:
        return 0
    _done, still = await asyncio.wait(pending, timeout=timeout_sec)
    for task in still:
        task.cancel()
    if still:
        log.warning("notify_batch.drain_timeout", cancelled=len(still), timeout_sec=timeout_sec)
    return len(still)
