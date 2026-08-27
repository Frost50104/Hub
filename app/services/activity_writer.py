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

from datetime import datetime
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
    created_at: datetime | None = None,
) -> None:
    """Insert one row into task_activity. Caller must commit later.

    `created_at` — ТОЛЬКО для переноса истории из внешнего трекера
    (`app/jobs/import_weeek_bundle.py`): у события должна стоять дата, когда
    задачу завели на самом деле, иначе архив 2022 года выглядит созданным
    в день импорта. Живой код его не передаёт — там прав `server_default now()`.
    """
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "actor_id": actor_id,
        "kind": kind,
        "payload": payload,
    }
    if created_at is not None:
        values["created_at"] = created_at
    await session.execute(insert(TaskActivity).values(**values))


async def record_activities(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Пачка событий одним INSERT. Только для переноса истории.

    Живой код пишет по событию за раз (`record_activity`) — там их и бывает
    одно. Импорт из внешнего трекера заводит по событию «создана» на каждую
    из тысяч задач, и 16 703 отдельных round-trip'а к базе — это минуты на
    ровном месте. Писатель `task_activity` при этом остаётся один: модуль.

    Каждая строка — {tenant_id, task_id, actor_id, kind, payload?, created_at?}.
    """
    if rows:
        await session.execute(insert(TaskActivity), rows)
