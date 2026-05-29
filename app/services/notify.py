"""Domain-specific notification builders.

Each helper composes title/body/url and calls `dispatch()` for a single
recipient. Caller loops over recipients (watchers, mentioned, assignee).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.services.notification_dispatcher import dispatch

STATUS_LABEL_RU = {
    "todo": "К выполнению",
    "in_progress": "В работе",
    "in_review": "На проверке",
    "done": "Готово",
}


def _task_url(task: Task) -> str:
    return f"/projects/{task.project_id}?task={task.id}"


def _truncate(text: str, n: int = 80) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[:n].rstrip() + "…"


async def notify_assigned(
    session: AsyncSession,
    *,
    task: Task,
    assignee_id: UUID,
    actor_name: str,
) -> None:
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=assignee_id,
        kind="task.assigned_to_me",
        title="Вам назначена задача",
        body=f"{actor_name} назначил вам «{task.title}»",
        url=_task_url(task),
        payload={"task_id": str(task.id), "actor_name": actor_name},
    )


async def notify_status_changed(
    session: AsyncSession,
    *,
    task: Task,
    new_status: str,
    actor_name: str,
    recipient_id: UUID,
) -> None:
    label = STATUS_LABEL_RU.get(new_status, new_status)
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=recipient_id,
        kind="task.status_changed_on_watched",
        title="Статус задачи изменён",
        body=f"{actor_name} перевёл «{task.title}» в «{label}»",
        url=_task_url(task),
        payload={"task_id": str(task.id), "new_status": new_status},
    )


async def notify_mentioned(
    session: AsyncSession,
    *,
    task: Task,
    comment_body: str,
    actor_name: str,
    recipient_id: UUID,
) -> None:
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=recipient_id,
        kind="task.mentioned",
        title=f"{actor_name} упомянул вас",
        body=f"«{task.title}»: {_truncate(comment_body)}",
        url=_task_url(task),
        payload={"task_id": str(task.id)},
    )


async def notify_commented(
    session: AsyncSession,
    *,
    task: Task,
    comment_body: str,
    actor_name: str,
    recipient_id: UUID,
) -> None:
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=recipient_id,
        kind="task.commented_on_watched",
        title="Новый комментарий",
        body=f"{actor_name} в «{task.title}»: {_truncate(comment_body)}",
        url=_task_url(task),
        payload={"task_id": str(task.id)},
    )


async def notify_due_soon(
    session: AsyncSession,
    *,
    task: Task,
    recipient_id: UUID,
) -> None:
    when = (
        task.due_at.strftime("%d.%m в %H:%M") if task.due_at else "скоро"
    )
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=recipient_id,
        kind="task.due_soon",
        title="Скоро дедлайн",
        body=f"«{task.title}» — срок {when}",
        url=_task_url(task),
        payload={
            "task_id": str(task.id),
            "due_at": task.due_at.isoformat() if task.due_at else None,
        },
    )


async def notify_overdue(
    session: AsyncSession,
    *,
    task: Task,
    recipient_id: UUID,
) -> None:
    await dispatch(
        session,
        tenant_id=task.tenant_id,
        employee_id=recipient_id,
        kind="task.overdue",
        title="Задача просрочена",
        body=f"«{task.title}» — дедлайн прошёл, статус ещё не «Готово»",
        url=_task_url(task),
        payload={
            "task_id": str(task.id),
            "due_at": task.due_at.isoformat() if task.due_at else None,
        },
    )
