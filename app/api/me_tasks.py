"""GET /api/me/tasks — current user's assigned tasks across all projects.

Used on the Home dashboard widget and the standalone /my page. Filters:
`status` (todo|in_progress|in_review|done), `due_window` (overdue|today|upcoming|all).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.project import Project
from app.models.stage import ProjectStage
from app.models.task import Task
from app.schemas.task import TaskResponse
from app.services.personal_projects import not_my_personal
from app.services.task_assignees import (
    assignee_exists,
    load_assignees,
    serialize_with_assignees,
)
from app.services.taskdates import (
    overdue_clause,
    start_of_today_utc,
    start_of_tomorrow_utc,
)
from app.services.tasks import apply_done_filter, reject_legacy_status

router = APIRouter(tags=["me-tasks"])

DueWindow = Literal["overdue", "today", "upcoming", "all"]


@router.get("/me/tasks", response_model=list[TaskResponse])
async def list_my_tasks(
    done: bool | None = Query(default=None),
    # LEGACY (0044): см. `_reject_legacy_status` в api/tasks.py.
    status_: str | None = Query(default=None, alias="status"),
    due_window: DueWindow | None = Query(default=None),
    include_archived: bool = Query(default=False),
    # Задачи СВОЕГО личного проекта у окон отбираем: на /my для них отдельная
    # секция «ЛИЧНОЕ», и одна задача не должна стоять на экране дважды. Задачи
    # из ЧУЖОГО личного, назначенные мне, остаются — это обычная работа.
    include_personal: bool = Query(default=False),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    reject_legacy_status(status_)
    # EXISTS, а не JOIN на task_assignees: JOIN размножил бы задачу по числу
    # исполнителей и дал дубли в списке. Семантика — «я СРЕДИ исполнителей».
    stmt = (
        select(Task, Project.key, ProjectStage.name)
        # key проекта — для бейджа «KEY-42» в кросс-проектном списке,
        # имя колонки — единственный признак прогресса в чужом проекте.
        .join(Project, Project.id == Task.project_id)
        # LEFT JOIN обязателен: у задачи может не быть статуса (0046), и INNER
        # выкинул бы её из «Моих задач» целиком — вместе с назначением.
        .outerjoin(ProjectStage, ProjectStage.id == Task.stage_id)
        .where(assignee_exists(principal.employee_id))
        .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None))
    if not include_personal:
        stmt = stmt.where(not_my_personal(principal.employee_id))
    stmt = apply_done_filter(stmt, done)

    # Окна — по КАЛЕНДАРНЫМ дням display tz (services/taskdates.py), не по
    # now(): задача со сроком сегодня после полудня — в «Сегодня» и
    # «Предстоит», а не в «Просрочено» (ОС тестировщика 2026-08).
    now = datetime.now(UTC)
    if due_window == "overdue":
        stmt = stmt.where(overdue_clause(now))
    elif due_window == "today":
        # «Сегодня» = просроченные (не done) + всё со сроком сегодня
        # (решение владельца 2026-08-21, как в Asana).
        stmt = stmt.where(
            Task.due_at < start_of_tomorrow_utc(now),
            or_(Task.done.is_(False), Task.due_at >= start_of_today_utc(now)),
        )
    elif due_window == "upcoming":
        stmt = stmt.where(Task.due_at >= start_of_today_utc(now), Task.done.is_(False))

    rows = (await db.execute(stmt)).all()
    by_task = await load_assignees(db, [task.id for task, _, _ in rows])
    out: list[TaskResponse] = []
    for task, project_key, stage_name in rows:
        data = serialize_with_assignees(task, by_task.get(task.id, []))
        data.project_key = project_key
        data.stage_name = stage_name
        out.append(data)
    return out
