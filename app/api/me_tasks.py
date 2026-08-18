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
from app.models.project import Project
from app.models.task import Task
from app.schemas.task import TaskResponse, TaskStatus
from app.services.task_assignees import (
    assignee_exists,
    load_assignees,
    serialize_with_assignees,
)

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
    # EXISTS, а не JOIN на task_assignees: JOIN размножил бы задачу по числу
    # исполнителей и дал дубли в списке. Семантика — «я СРЕДИ исполнителей».
    stmt = (
        select(Task, Project.key)
        # key проекта — для бейджа «KEY-42» в кросс-проектном списке.
        .join(Project, Project.id == Task.project_id)
        .where(assignee_exists(principal.employee_id))
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

    rows = (await db.execute(stmt)).all()
    by_task = await load_assignees(db, [task.id for task, _ in rows])
    out: list[TaskResponse] = []
    for task, project_key in rows:
        data = serialize_with_assignees(task, by_task.get(task.id, []))
        data.project_key = project_key
        out.append(data)
    return out
