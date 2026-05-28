"""GET /api/me/tasks — current user's assigned tasks across all projects.

Used on the Home dashboard widget and the standalone /my page. Filters:
`status` (todo|in_progress|in_review|done), `due_window` (overdue|today|upcoming|all).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.task import AssigneeBrief, TaskResponse, TaskStatus

router = APIRouter(tags=["me-tasks"])

DueWindow = Literal["overdue", "today", "upcoming", "all"]


@router.get("/me/tasks", response_model=list[TaskResponse])
async def list_my_tasks(
    status_: TaskStatus | None = Query(default=None, alias="status"),
    due_window: DueWindow | None = Query(default=None),
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    stmt = (
        select(Task, ShadowUser.email, ShadowUser.full_name)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == Task.assignee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Task.assignee_id == principal.employee_id)
        .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None))
    if status_ is not None:
        stmt = stmt.where(Task.status == status_)

    now = datetime.now(UTC)
    if due_window == "overdue":
        stmt = stmt.where(Task.due_at < now, Task.status != "done")
    elif due_window == "today":
        today_end = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        stmt = stmt.where(Task.due_at >= now, Task.due_at < today_end)
    elif due_window == "upcoming":
        stmt = stmt.where(Task.due_at >= now, Task.status != "done")

    out: list[TaskResponse] = []
    for task, email, full_name in (await db.execute(stmt)).all():
        assignee = (
            AssigneeBrief(employee_id=task.assignee_id, email=email, full_name=full_name)
            if task.assignee_id
            else None
        )
        data = TaskResponse.model_validate(task)
        data.assignee = assignee
        out.append(data)
    return out
