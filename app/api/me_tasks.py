"""GET /api/me/tasks — задачи, назначенные на меня, по всем проектам.

Кормит панель «Главной» и страницу `/my`. Фильтры: `done`, `due_window`
(overdue|today|upcoming|all), `include_archived`, `include_personal`.

Архивный проект сюда не попадает (31.08): архив значит «запарковано» — задачи
уходят из личных списков и перестают порождать дедлайнные пуши. Правило одно на
`/me/stats`, `jobs/due_soon.py`, `jobs/overdue.py` и инструменты ассистента,
предикат — `services/projects.py::project_not_archived`.
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
from app.services.projects import project_not_archived
from app.services.task_assignees import (
    assignee_exists,
    load_assignees,
    serialize_with_assignees,
)
from app.services.task_recurrence import load_rules, recurrence_info
from app.services.taskdates import (
    display_today,
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
    # «Архивное вообще»: и архивные ЗАДАЧИ, и задачи архивных ПРОЕКТОВ. Флаг
    # один, потому что смысл один — «покажи убранное»; клиент его не шлёт
    # (вход в архив — пункт сайдбара «Архив», а не фильтр этого списка).
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
        # Два РАЗНЫХ архива в одной строке: задачи и её проекта. Проект — через
        # предикат `project_not_archived()`, потому что правило кросс-проектное
        # и живёт ещё в `/me/stats`, двух cron-джобах и инструментах ассистента;
        # джойн на `projects` здесь уже есть (выше, ради `Project.key`), так что
        # условие бесплатное.
        stmt = stmt.where(Task.archived_at.is_(None), project_not_archived())
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
    ids = [task.id for task, _, _ in rows]
    by_task = await load_assignees(db, ids)
    rules = await load_rules(db, ids)
    today = display_today(now)
    out: list[TaskResponse] = []
    for task, project_key, stage_name in rows:
        data = serialize_with_assignees(task, by_task.get(task.id, []))
        data.recurrence = recurrence_info(rules.get(task.id), today=today)
        data.project_key = project_key
        data.stage_name = stage_name
        out.append(data)
    return out
