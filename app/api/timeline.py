"""Timeline / Gantt endpoint (Phase 4.3).

`GET /api/projects/{project_id}/timeline?from=YYYY-MM-DD&to=YYYY-MM-DD`
returns:
- tasks that overlap the window (same overlap rule as `/calendar`)
- with `include_undated=1` — also tasks WITHOUT a due date: the Gantt draws
  a row for them without a bar and counts «N без срока» (redesign 2026-08).
  The parameter is new, so older PWA bundles keep getting dated tasks only.
- dependencies among them (edges where BOTH endpoints land in the window)

Same auth rules as `/calendar` — viewer+ on project. MAX 366 day window
(Calendar caps at 92; Timeline often shows months of work).
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.dependency import TaskDependency
from app.models.task import Task
from app.schemas.dependency import TaskDependencyResponse
from app.schemas.task import TaskResponse
from app.services.personal_projects import assert_full_project_access
from app.services.project_access import require_project_role
from app.services.task_assignees import load_assignees, serialize_with_assignees
from app.services.taskdates import day_start_utc

router = APIRouter(tags=["timeline"])

_MAX_RANGE_DAYS = 366


class TimelineResponse(BaseModel):
    tasks: list[TaskResponse]
    dependencies: list[TaskDependencyResponse]


def _parse_iso_date(raw: str, *, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Параметр {field} должен быть YYYY-MM-DD",
        ) from e


@router.get(
    "/projects/{project_id}/timeline", response_model=TimelineResponse
)
async def get_timeline(
    project_id: UUID,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    include_undated: bool = Query(False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    project, _ = await require_project_role(db, project_id, principal)
    assert_full_project_access(project, principal)

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
            detail=f"Окно > {_MAX_RANGE_DAYS} дней",
        )

    # Границы дней — display tz (срок задачи = календарный день, taskdates).
    from_dt = day_start_utc(from_date)
    to_dt = day_start_utc(to_date + timedelta(days=1))

    # ─── Tasks overlapping the window ───────────────────────────────────────
    overlaps = (Task.due_at.is_not(None)) & or_(
        (Task.start_at.is_(None)) & (Task.due_at >= from_dt) & (Task.due_at < to_dt),
        (Task.start_at.is_not(None)) & (Task.start_at < to_dt) & (Task.due_at >= from_dt),
    )
    # Задачи без срока — только по явной просьбе: строка есть, полосы нет.
    window = or_(overlaps, Task.due_at.is_(None)) if include_undated else overlaps
    task_stmt = (
        # Без JOIN на исполнителей — размножил бы задачу по их числу
        # (дубли полос на диаграмме). Исполнители едут батчем ниже.
        select(Task)
        .where(Task.project_id == project_id, Task.archived_at.is_(None), window)
        # Секции больше нет — сортируем как список задач: позиция плюс
        # `seq` тай-брейкером, иначе при равных позициях порядок полос
        # менялся бы от запроса к запросу.
        .order_by(Task.position, Task.seq)
    )

    tasks = (await db.execute(task_stmt)).scalars().all()
    by_task = await load_assignees(db, [t.id for t in tasks])
    tasks_out: list[TaskResponse] = [
        serialize_with_assignees(t, by_task.get(t.id, [])) for t in tasks
    ]
    visible_ids: set[UUID] = {t.id for t in tasks}

    # ─── Dependencies confined to visible tasks ─────────────────────────────
    dep_out: list[TaskDependencyResponse] = []
    if visible_ids:
        dep_rows = await db.execute(
            select(TaskDependency).where(
                TaskDependency.predecessor_id.in_(visible_ids),
                TaskDependency.successor_id.in_(visible_ids),
            )
        )
        dep_out = [
            TaskDependencyResponse.model_validate(d) for d in dep_rows.scalars().all()
        ]


    return TimelineResponse(
        tasks=tasks_out, dependencies=dep_out
    )
