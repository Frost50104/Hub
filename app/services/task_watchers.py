"""Идемпотентная подписка на задачу.

Вынесено из `app/api/tasks.py` в 0034: `task_assignees.apply_side_effects`
подписывает каждого нового исполнителя, а импорт service → api дал бы цикл.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskWatcher


async def ensure_watcher(
    db: AsyncSession,
    *,
    task_id: UUID,
    tenant_id: UUID,
    employee_id: UUID,
    reason: str,
) -> None:
    """Idempotent watcher add — ON CONFLICT DO NOTHING.

    Doesn't upgrade the reason (creator stays creator even if also assigned);
    the original reason is more informative for activity rendering.
    """
    await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task_id,
            employee_id=employee_id,
            tenant_id=tenant_id,
            added_reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )
