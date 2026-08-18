"""Timeline / Gantt endpoint (Phase 4.3).

`GET /api/projects/{project_id}/timeline?from=YYYY-MM-DD&to=YYYY-MM-DD`
returns:
- tasks that overlap the window (same overlap rule as `/calendar`)
- dependencies among them (edges where BOTH endpoints land in the window)
- sections (UI groups bars by section)

Same auth rules as `/calendar` — viewer+ on project. MAX 366 day window
(Calendar caps at 92; Timeline often shows months of work).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.dependency import TaskDependency
from app.models.section import Section
from app.models.task import Task
from app.schemas.dependency import TaskDependencyResponse
from app.schemas.task import TaskResponse
from app.services.project_access import require_project_role
from app.services.task_assignees import load_assignees, serialize_with_assignees

router = APIRouter(tags=["timeline"])

_MAX_RANGE_DAYS = 366


class SectionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    position: int


class TimelineResponse(BaseModel):
    tasks: list[TaskResponse]
    dependencies: list[TaskDependencyResponse]
    sections: list[SectionBrief]


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
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
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
            detail=f"Окно > {_MAX_RANGE_DAYS} дней",
        )

    from_dt = datetime.combine(from_date, time(0, 0, 0), tzinfo=UTC)
    to_dt = datetime.combine(to_date + timedelta(days=1), time(0, 0, 0), tzinfo=UTC)

    # ─── Tasks overlapping the window ───────────────────────────────────────
    task_stmt = (
        # Без JOIN на исполнителей — размножил бы задачу по их числу
        # (дубли полос на диаграмме). Исполнители едут батчем ниже.
        select(Task)
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            Task.due_at.is_not(None),
            or_(
                (Task.start_at.is_(None)) & (Task.due_at >= from_dt) & (Task.due_at < to_dt),
                (Task.start_at.is_not(None))
                & (Task.start_at < to_dt)
                & (Task.due_at >= from_dt),
            ),
        )
        .order_by(Task.section_id.nulls_first(), Task.position)
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

    # ─── Sections — used for row grouping ───────────────────────────────────
    section_rows = await db.execute(
        select(Section)
        .where(Section.project_id == project_id)
        .order_by(Section.position)
    )
    sections = [
        SectionBrief.model_validate(s) for s in section_rows.scalars().all()
    ]

    return TimelineResponse(
        tasks=tasks_out, dependencies=dep_out, sections=sections
    )
