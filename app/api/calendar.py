"""Calendar view endpoint (3.6.9).

`GET /api/projects/{project_id}/tasks/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD`
returns every task whose `(start_at, due_at)` interval overlaps the requested
window. Single-day tasks (start_at IS NULL) are placed on `due_at`.

The window is closed at both ends in DAY granularity (`from` and `to` both
inclusive), converted to a half-open UTC datetime range internally:
    [from 00:00 UTC, (to + 1 day) 00:00 UTC).

We do NOT enforce a tenant timezone — assume Europe/Moscow displays via
client-side `toLocaleDateString`. Stretching the window by a day on each
side covers the small overlap; the front-end clips visually.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.task import Task
from app.schemas.task import TaskPriority, TaskResponse, TaskStatus
from app.services.project_access import require_project_role
from app.services.task_assignees import (
    assignee_exists,
    load_assignees,
    serialize_with_assignees,
)

router = APIRouter(tags=["calendar"])

_MAX_RANGE_DAYS = 92  # roughly a quarter — caps payload size + query cost.


def _parse_iso_date(raw: str, *, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Параметр {field} должен быть YYYY-MM-DD",
        ) from e


@router.get(
    "/projects/{project_id}/tasks/calendar",
    response_model=list[TaskResponse],
)
async def list_calendar_tasks(
    project_id: UUID,
    from_: str = Query(..., alias="from", description="Inclusive YYYY-MM-DD"),
    to: str = Query(..., description="Inclusive YYYY-MM-DD"),
    status_: TaskStatus | None = Query(default=None, alias="status"),
    assignee_id: UUID | None = Query(default=None, alias="assignee"),
    priority: TaskPriority | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    await require_project_role(db, project_id, principal)

    from_date = _parse_iso_date(from_, field="from")
    to_date = _parse_iso_date(to, field="to")
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`to` должна быть >= `from`",
        )
    if (to_date - from_date).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Окно > {_MAX_RANGE_DAYS} дней — слишком много для одного запроса",
        )

    # Half-open UTC range. `to_dt` = day after `to_date` at 00:00 → captures
    # everything that ended on `to_date` in any timezone reasonable for ops.
    from_dt = datetime.combine(from_date, time(0, 0, 0), tzinfo=UTC)
    to_dt = datetime.combine(to_date + timedelta(days=1), time(0, 0, 0), tzinfo=UTC)

    stmt = (
        # Без JOIN на исполнителей — он размножил бы задачу по их числу
        # (дубли событий в сетке). Исполнители едут батчем ниже.
        select(Task)
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            Task.due_at.is_not(None),
            or_(
                # Single-day: pinned to due_at only.
                (Task.start_at.is_(None)) & (Task.due_at >= from_dt) & (Task.due_at < to_dt),
                # Multi-day: any overlap with [from_dt, to_dt).
                (Task.start_at.is_not(None))
                & (Task.start_at < to_dt)
                & (Task.due_at >= from_dt),
            ),
        )
        .order_by(Task.start_at.nulls_last(), Task.due_at)
    )
    if status_ is not None:
        stmt = stmt.where(Task.status == status_)
    if assignee_id is not None:
        stmt = stmt.where(assignee_exists(assignee_id))
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)

    tasks = (await db.execute(stmt)).scalars().all()
    by_task = await load_assignees(db, [t.id for t in tasks])
    return [serialize_with_assignees(t, by_task.get(t.id, [])) for t in tasks]
