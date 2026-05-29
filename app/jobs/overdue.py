"""Daily cron (09:00 MSK / 06:00 UTC): notify watchers + assignee about
overdue tasks (due_at < now, status != done).

Anti-dup: 23 hours window — only one overdue reminder per task per user per day.

Run via systemd: `signaris-hub[-staging]-overdue.timer`
(OnCalendar=*-*-* 06:00:00 = 09:00 Moscow time).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from app import log as log_config
from app.db import tenant_scoped_session
from app.jobs._common import already_notified
from app.models.task import Task, TaskWatcher
from app.services.notify import notify_overdue

log = structlog.get_logger("jobs.overdue")

ANTI_DUP_WINDOW = timedelta(hours=23)


async def main() -> int:
    log_config.configure()
    now = datetime.now(UTC)
    log.info("overdue.started", now=now.isoformat())

    sent_total = 0
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        tasks = (
            await session.execute(
                select(Task).where(
                    Task.due_at.is_not(None),
                    Task.due_at < now,
                    Task.status != "done",
                    Task.archived_at.is_(None),
                )
            )
        ).scalars().all()
        log.info("overdue.scanned", task_count=len(tasks))

        for task in tasks:
            watcher_rows = await session.execute(
                select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
            )
            recipients = {row[0] for row in watcher_rows.all()}
            if task.assignee_id:
                recipients.add(task.assignee_id)

            for emp_id in recipients:
                if await already_notified(
                    session,
                    employee_id=emp_id,
                    task_id=task.id,
                    kind="task.overdue",
                    within=ANTI_DUP_WINDOW,
                    now=now,
                ):
                    continue
                await notify_overdue(session, task=task, recipient_id=emp_id)
                sent_total += 1

        await session.commit()

    log.info("overdue.finished", sent=sent_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
