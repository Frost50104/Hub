"""Shared helpers for cron jobs (`due_soon`, `overdue`, …).

All jobs:
- run as one-shot processes via systemd timers,
- open ONE `tenant_scoped_session(None, bypass_rls=True)` to scan tasks across
  all tenants (these are system workers, not user-scoped requests),
- use `payload->>'task_id'` to deduplicate per recipient inside a recent window.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession


async def already_notified(
    session: AsyncSession,
    *,
    employee_id: UUID,
    task_id: UUID,
    kind: str,
    within: timedelta,
    now: datetime,
) -> bool:
    """Whether a `kind` notification for this task+employee was sent within `within` of `now`."""
    threshold = now - within
    row = await session.execute(
        sa_text(
            "SELECT 1 FROM notifications "
            "WHERE employee_id = :emp "
            "AND kind = :kind "
            "AND created_at > :since "
            "AND payload->>'task_id' = :task_id "
            "LIMIT 1"
        ),
        {
            "emp": str(employee_id),
            "kind": kind,
            "since": threshold,
            "task_id": str(task_id),
        },
    )
    return row.scalar_one_or_none() is not None
