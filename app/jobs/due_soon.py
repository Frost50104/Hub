"""Hourly cron: notify watchers + assignee about tasks due within 24h.

Anti-dup: for each (recipient, task) pair we skip if a `task.due_soon`
notification was already created within the last 23 hours — so even at
hourly granularity we send at most one reminder per day per task per user.

Run via systemd: `signaris-hub[-staging]-due-soon.timer` (OnCalendar=hourly).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from app import log as log_config
from app.db import tenant_scoped_session
from app.jobs._common import already_notified
from app.models.project import Project
from app.models.task import Task
from app.services.notify import notify_due_soon
from app.services.projects import project_not_archived
from app.services.task_assignees import collect_recipients

log = structlog.get_logger("jobs.due_soon")

ANTI_DUP_WINDOW = timedelta(hours=23)
# Окно НАРОЧНО по мгновению, а не по дням (в отличие от overdue/окон
# /me/tasks): срок пишется на 12:00 display tz, и «за сутки» = push около
# полудня накануне; день-окно с 00:00 слало бы напоминание ночью.
LOOKAHEAD_WINDOW = timedelta(hours=24)


def scan_stmt(now: datetime):
    """Задачи, по которым сейчас шлём «срок завтра».

    Вынесено из `main()` ради теста: сам джоб тестами не покрыт — ровно та
    причина, по которой из него уже вынесен `collect_recipients` (докстринг
    `tests/integration/test_job_recipients.py`).

    `project_not_archived()` здесь не косметика: архивный проект запаркован,
    его задачи ушли из «Моих задач», и напоминание звонило бы человеку по
    работе, которую он сам убрал с глаз. Событийные пуши (назначение,
    упоминание, комментарий) архив не гасит — за ними стоит живое действие.

    JOIN INNER безопасен: `tasks.project_id` NOT NULL.
    """
    return (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.due_at.is_not(None),
            Task.due_at >= now,
            Task.due_at < now + LOOKAHEAD_WINDOW,
            Task.done.is_(False),
            Task.archived_at.is_(None),
            project_not_archived(),
        )
    )


async def main() -> int:
    log_config.configure()
    now = datetime.now(UTC)
    upper = now + LOOKAHEAD_WINDOW
    log.info("due_soon.started", now=now.isoformat(), upper=upper.isoformat())

    sent_total = 0
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        tasks = (await session.execute(scan_stmt(now))).scalars().all()
        log.info("due_soon.scanned", task_count=len(tasks))

        # Один батч на всю выборку вместо запроса за watcher'ами на задачу.
        recipients_by_task = await collect_recipients(session, [t.id for t in tasks])

        for task in tasks:
            recipients = recipients_by_task.get(task.id, set())

            for emp_id in recipients:
                if await already_notified(
                    session,
                    employee_id=emp_id,
                    task_id=task.id,
                    kind="task.due_soon",
                    within=ANTI_DUP_WINDOW,
                    now=now,
                ):
                    continue
                await notify_due_soon(session, task=task, recipient_id=emp_id)
                sent_total += 1

        await session.commit()

    log.info("due_soon.finished", sent=sent_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
