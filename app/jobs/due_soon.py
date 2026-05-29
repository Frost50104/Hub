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
from app.models.task import Task, TaskWatcher
from app.services.notify import notify_due_soon

log = structlog.get_logger("jobs.due_soon")

ANTI_DUP_WINDOW = timedelta(hours=23)
LOOKAHEAD_WINDOW = timedelta(hours=24)


async def main() -> int:
    log_config.configure()
    now = datetime.now(UTC)
    upper = now + LOOKAHEAD_WINDOW
    log.info("due_soon.started", now=now.isoformat(), upper=upper.isoformat())

    sent_total = 0
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        tasks = (
            await session.execute(
                select(Task).where(
                    Task.due_at.is_not(None),
                    Task.due_at >= now,
                    Task.due_at < upper,
                    Task.status != "done",
                    Task.archived_at.is_(None),
                )
            )
        ).scalars().all()
        log.info("due_soon.scanned", task_count=len(tasks))

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
