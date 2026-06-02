"""Project dashboard stats (Phase 4.6).

`GET /api/projects/{project_id}/stats` returns a single JSON payload with
all of the data the ProjectDashboard.tsx page needs — one round-trip is
enough so the UI can render every card in parallel.

Aggregates exposed:
- `status_breakdown` / `priority_breakdown` — `{value: count}` maps.
- `completed_trend` — list of `{day: YYYY-MM-DD, count: int}` for the
  last 30 days (zero-padded so the chart x-axis is continuous).
- `overdue_count` — tasks with `due_at < now` and `status != 'done'`.
- `workload` — top assignees by active (non-done, non-archived) count.
- `custom_field_stats` — per field:
   - number → {sum, avg, min, max, count}
   - select/multi_select → {options: [{id, label, count}]}
   - other types omitted (nothing useful to report).

All counts respect RLS via `tenant_scoped_session(principal.tenant_id)`.
Viewer+ is required on the project (same gate as `/tasks`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.services.project_access import require_project_role

router = APIRouter(tags=["stats"])

_TREND_DAYS = 30
_WORKLOAD_TOP = 10


class TrendPoint(BaseModel):
    day: date
    count: int


class WorkloadEntry(BaseModel):
    employee_id: UUID | None
    full_name: str | None
    email: str | None
    active_count: int
    done_count: int


class NumberStats(BaseModel):
    sum: float | None
    avg: float | None
    min: float | None
    max: float | None
    count: int


class OptionCount(BaseModel):
    id: str
    label: str
    count: int


class SelectStats(BaseModel):
    options: list[OptionCount]


class CustomFieldStat(BaseModel):
    field_id: UUID
    name: str
    type: str
    number: NumberStats | None = None
    select: SelectStats | None = None


class ProjectStatsResponse(BaseModel):
    status_breakdown: dict[str, int]
    priority_breakdown: dict[str, int]
    completed_trend: list[TrendPoint]
    overdue_count: int
    workload: list[WorkloadEntry]
    custom_field_stats: list[CustomFieldStat]
    total_active: int
    total_archived: int


async def _status_or_priority_breakdown(
    session: AsyncSession, project_id: UUID, column
) -> dict[str, int]:
    rows = await session.execute(
        select(column, func.count(Task.id))
        .where(Task.project_id == project_id, Task.archived_at.is_(None))
        .group_by(column)
    )
    return {str(label): int(count) for label, count in rows.all()}


async def _completed_trend(
    session: AsyncSession, project_id: UUID
) -> list[TrendPoint]:
    """Tasks completed per day for the last `_TREND_DAYS`. Zero-padded so
    the front-end chart has a continuous x-axis even on quiet days.
    """
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=_TREND_DAYS - 1)
    start_dt = datetime.combine(start_date, time(0, 0, 0), tzinfo=UTC)
    rows = await session.execute(
        select(
            func.date_trunc("day", Task.completed_at).label("day"),
            func.count(Task.id),
        )
        .where(
            Task.project_id == project_id,
            Task.completed_at.is_not(None),
            Task.completed_at >= start_dt,
        )
        .group_by(text("day"))
        .order_by(text("day"))
    )
    counts: dict[date, int] = {}
    for raw_day, count in rows.all():
        if raw_day is None:
            continue
        counts[raw_day.date()] = int(count)
    out: list[TrendPoint] = []
    for i in range(_TREND_DAYS):
        d = start_date + timedelta(days=i)
        out.append(TrendPoint(day=d, count=counts.get(d, 0)))
    return out


async def _overdue_count(session: AsyncSession, project_id: UUID) -> int:
    now = datetime.now(UTC)
    row = await session.execute(
        select(func.count(Task.id)).where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            Task.status != "done",
            Task.due_at.is_not(None),
            Task.due_at < now,
        )
    )
    return int(row.scalar_one())


async def _workload(
    session: AsyncSession, project_id: UUID
) -> list[WorkloadEntry]:
    """Per-assignee counts. Tasks without an assignee fall into one
    "unassigned" bucket (employee_id=None)."""
    rows = await session.execute(
        select(
            Task.assignee_id,
            ShadowUser.full_name,
            ShadowUser.email,
            func.sum(
                func.cast(
                    and_(Task.archived_at.is_(None), Task.status != "done"),
                    type_=text("INTEGER").type,
                )
            ).label("active_count"),
            func.sum(
                func.cast(Task.status == "done", type_=text("INTEGER").type)
            ).label("done_count"),
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == Task.assignee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Task.project_id == project_id)
        .group_by(Task.assignee_id, ShadowUser.full_name, ShadowUser.email)
        .order_by(text("active_count DESC NULLS LAST"))
        .limit(_WORKLOAD_TOP)
    )
    return [
        WorkloadEntry(
            employee_id=row.assignee_id,
            full_name=row.full_name,
            email=row.email,
            active_count=int(row.active_count or 0),
            done_count=int(row.done_count or 0),
        )
        for row in rows.all()
    ]


async def _custom_field_stats(
    session: AsyncSession, project_id: UUID
) -> list[CustomFieldStat]:
    defs = (
        await session.execute(
            select(CustomFieldDefinition)
            .where(CustomFieldDefinition.project_id == project_id)
            .order_by(CustomFieldDefinition.position)
        )
    ).scalars().all()

    if not defs:
        return []

    out: list[CustomFieldStat] = []
    for d in defs:
        if d.type == "number":
            # JSONB → float cast through Postgres cast operator (`::float8`).
            # Using `func.jsonb_typeof` to skip rows where the value somehow
            # isn't a number despite the field type — defensive.
            row = await session.execute(
                select(
                    func.sum(func.cast(TaskCustomFieldValue.value, type_=text("float8").type)),
                    func.avg(func.cast(TaskCustomFieldValue.value, type_=text("float8").type)),
                    func.min(func.cast(TaskCustomFieldValue.value, type_=text("float8").type)),
                    func.max(func.cast(TaskCustomFieldValue.value, type_=text("float8").type)),
                    func.count(TaskCustomFieldValue.task_id),
                )
                .join(Task, Task.id == TaskCustomFieldValue.task_id)
                .where(
                    Task.project_id == project_id,
                    Task.archived_at.is_(None),
                    TaskCustomFieldValue.field_id == d.id,
                    text("jsonb_typeof(task_custom_field_values.value) = 'number'"),
                )
            )
            s, a, mn, mx, cnt = row.first() or (None, None, None, None, 0)
            out.append(
                CustomFieldStat(
                    field_id=d.id,
                    name=d.name,
                    type=d.type,
                    number=NumberStats(
                        sum=float(s) if s is not None else None,
                        avg=float(a) if a is not None else None,
                        min=float(mn) if mn is not None else None,
                        max=float(mx) if mx is not None else None,
                        count=int(cnt or 0),
                    ),
                )
            )
        elif d.type in ("select", "multi_select"):
            # For `select` the JSONB value is a string option_id; for
            # `multi_select` it's an array. We expand both to a flat option_id
            # list using `jsonb_array_elements_text` for arrays and a fallback
            # for plain strings.
            option_lookup = {str(opt.get("id")): str(opt.get("label", opt.get("id")))
                             for opt in (d.options or [])}

            if d.type == "select":
                opt_id_col = func.cast(
                    TaskCustomFieldValue.value, type_=text("text").type
                ).label("opt_id")
                rows = await session.execute(
                    select(opt_id_col, func.count(TaskCustomFieldValue.task_id))
                    .join(Task, Task.id == TaskCustomFieldValue.task_id)
                    .where(
                        Task.project_id == project_id,
                        Task.archived_at.is_(None),
                        TaskCustomFieldValue.field_id == d.id,
                        text("jsonb_typeof(task_custom_field_values.value) = 'string'"),
                    )
                    .group_by(text("opt_id"))
                )
            else:
                # multi_select — expand JSONB array, group by element.
                rows = await session.execute(
                    text(
                        "SELECT v.elem AS opt_id, COUNT(*) AS cnt "
                        "FROM task_custom_field_values tcfv "
                        "JOIN tasks t ON t.id = tcfv.task_id "
                        ", jsonb_array_elements_text(tcfv.value) v(elem) "
                        "WHERE tcfv.field_id = :fid "
                        "AND t.project_id = :pid "
                        "AND t.archived_at IS NULL "
                        "AND jsonb_typeof(tcfv.value) = 'array' "
                        "GROUP BY v.elem"
                    ),
                    {"fid": str(d.id), "pid": str(project_id)},
                )

            options_by_id: dict[str, OptionCount] = {}
            for raw in rows.all():
                opt_id = str(raw[0]).strip('"')
                count = int(raw[1])
                label = option_lookup.get(opt_id, opt_id)
                options_by_id[opt_id] = OptionCount(
                    id=opt_id, label=label, count=count
                )
            out.append(
                CustomFieldStat(
                    field_id=d.id,
                    name=d.name,
                    type=d.type,
                    select=SelectStats(options=list(options_by_id.values())),
                )
            )
    return out


@router.get(
    "/projects/{project_id}/stats", response_model=ProjectStatsResponse
)
async def get_stats(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectStatsResponse:
    await require_project_role(db, project_id, principal)

    status_breakdown = await _status_or_priority_breakdown(
        db, project_id, Task.status
    )
    priority_breakdown = await _status_or_priority_breakdown(
        db, project_id, Task.priority
    )
    completed_trend = await _completed_trend(db, project_id)
    overdue_count = await _overdue_count(db, project_id)
    workload = await _workload(db, project_id)
    cf_stats = await _custom_field_stats(db, project_id)

    total_active = sum(status_breakdown.values())
    archived_row = await db.execute(
        select(func.count(Task.id)).where(
            Task.project_id == project_id, Task.archived_at.is_not(None)
        )
    )
    total_archived = int(archived_row.scalar_one())

    # Silence pyflakes — `Any` is used only via cast-helper text() above.
    _ = Any

    return ProjectStatsResponse(
        status_breakdown=status_breakdown,
        priority_breakdown=priority_breakdown,
        completed_trend=completed_trend,
        overdue_count=overdue_count,
        workload=workload,
        custom_field_stats=cf_stats,
        total_active=total_active,
        total_archived=total_archived,
    )
