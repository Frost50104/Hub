"""Domain-specific notification builders.

Each helper composes title/body/url and calls `dispatch()` for a single
recipient. Caller loops over recipients (watchers, mentioned, assignee).

Все задачные уведомления идут через `_send`: задача ШАБЛОНА (0060) не шлёт
ничего — ни назначение, ни выполнение, ни упоминание. Шаблон — заготовка, а
не работа; люди из него узнают о задачах одним сводным уведомлением, когда по
шаблону создают проект (`notify_assigned_from_template`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.services.notification_dispatcher import dispatch
from app.services.ru_plural import ru_plural
from app.services.timefmt import fmt_dt


def _task_url(task: Task) -> str:
    return f"/projects/{task.project_id}?task={task.id}"


def _truncate(text: str, n: int = 80) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[:n].rstrip() + "…"


async def _send(session: AsyncSession, task: Task, **kwargs) -> None:
    """Общая горловина задачных уведомлений; шаблон молчит (см. модуль)."""
    if task.is_template:
        return
    await dispatch(session, tenant_id=task.tenant_id, **kwargs)


async def notify_assigned(
    session: AsyncSession,
    *,
    task: Task,
    assignee_id: UUID,
    actor_name: str,
) -> None:
    await _send(
        session,
        task,
        employee_id=assignee_id,
        kind="task.assigned_to_me",
        title="Вам назначена задача",
        body=f"{actor_name} назначил вам «{task.title}»",
        url=_task_url(task),
        payload={"task_id": str(task.id), "actor_name": actor_name},
    )


async def notify_done_changed(
    session: AsyncSession,
    *,
    task: Task,
    done: bool,
    actor_name: str,
    recipient_id: UUID,
) -> None:
    """Задачу выполнили или вернули в работу.

    Kind НЕ переименован (`task.status_changed_on_watched`) сознательно: ключи
    лежат в JSONB-настройках людей (`notification_prefs`), и смена ключа
    вернула бы пуш тем, кто его отключил. Перенос между колонками уведомления
    не шлёт — только лента.
    """
    await _send(
        session,
        task,
        employee_id=recipient_id,
        kind="task.status_changed_on_watched",
        title="Задача выполнена" if done else "Задача вернулась в работу",
        body=(
            f"{actor_name} выполнил «{task.title}»"
            if done
            else f"{actor_name} вернул «{task.title}» в работу"
        ),
        url=_task_url(task),
        payload={"task_id": str(task.id), "done": done},
    )


async def notify_mentioned(
    session: AsyncSession,
    *,
    task: Task,
    comment_body: str,
    actor_name: str,
    recipient_id: UUID,
) -> None:
    await _send(
        session,
        task,
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
    await _send(
        session,
        task,
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
    when = fmt_dt(task.due_at, "%d.%m в %H:%M") if task.due_at else "скоро"
    await _send(
        session,
        task,
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
    await _send(
        session,
        task,
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


async def notify_assigned_from_template(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    project_name: str,
    template_id: UUID,
    recipient_id: UUID,
    task_count: int,
) -> None:
    """Одно сводное уведомление на человека при создании проекта по шаблону.

    Вид — существующий `task.assigned_to_me`: настройки сверяются по виду, и
    кто выключил «Назначили задачу», не получит и сводку. Ссылка начинается с
    `/projects/{id}` — удаление проекта уносит строку «Входящих» само
    (`projects.py`, чистка по `url LIKE`), а `f_assignee` понимают и старые
    бандлы. Звать ПОСЛЕ commit копии: `dispatch` планирует пуш сразу.
    """
    await dispatch(
        session,
        tenant_id=tenant_id,
        employee_id=recipient_id,
        kind="task.assigned_to_me",
        title=f"Новый проект «{_truncate(project_name, 60)}»",
        body=f"В проекте для вас {ru_plural(task_count, 'задача', 'задачи', 'задач')}",
        url=f"/projects/{project_id}?f_assignee={recipient_id}",
        payload={
            "project_id": str(project_id),
            "template_id": str(template_id),
            "count": task_count,
        },
    )
