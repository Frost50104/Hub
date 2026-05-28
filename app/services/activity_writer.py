"""Append-only writer for task_activity.

`record_activity` is called by tasks/comments/watchers handlers right after
the domain mutation, BEFORE `session.commit()`. The activity row participates
in the same transaction — partial states are impossible.

Kinds (extended as features land):
- 3a tasks: `created`, `updated`, `status_changed`, `assigned`, `unassigned`,
  `archived`, `unarchived`, `deleted`, `due_changed`, `priority_changed`,
  `moved` (section change).
- 3b canban: `reordered` (position-only updates without status change).
- 3c comments/watchers: `commented`, `comment_edited`, `comment_deleted`,
  `watcher_added`, `watcher_removed`.
- 3d labels: `labeled`, `unlabeled`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskActivity


async def record_activity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    task_id: UUID,
    actor_id: UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert one row into task_activity. Caller must commit later."""
    await session.execute(
        insert(TaskActivity).values(
            tenant_id=tenant_id,
            task_id=task_id,
            actor_id=actor_id,
            kind=kind,
            payload=payload,
        )
    )
