"""Tasks API (Hub-MVP.3a). CRUD + status/assignee/due changes +
archive. Drag-reorder via PATCH `position` lands in 3b; watchers/comments
land in 3c.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.attachment import TaskAttachment
from app.models.notification import Notification
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.models.stage import ProjectStage
from app.models.task import Task, TaskLabelAssignment, TaskRecurrence, TaskWatcher
from app.schemas.task import (
    TaskAssigneeAdd,
    TaskCreate,
    TaskMoveReport,
    TaskMoveRequest,
    TaskPriority,
    TaskRecurrenceBody,
    TaskResponse,
    TaskUpdate,
    resolve_assignee_ids,
)
from app.services.activity_writer import record_activity
from app.services.attachments import purge_blobs
from app.services.notify import notify_done_changed
from app.services.personal_projects import personal_task_scope, require_task_access
from app.services.project_access import (
    EDIT_ROLES,
    ProjectRole,
    is_hub_admin,
    require_project_role,
)
from app.services.recurrence_dates import describe
from app.services.stages import get_stage_in_project, set_done, set_stage
from app.services.task_assignees import (
    add_assignee,
    apply_assignee_side_effects,
    assignee_exists,
    can_complete,
    is_task_assignee,
    load_assignees,
    remove_assignee,
    serialize_with_assignees,
    set_task_assignees,
)
from app.services.task_counts import load_row_counts
from app.services.task_move import MovePlan, apply_move, plan_move
from app.services.task_recurrence import (
    claim_rule,
    load_rule,
    load_rules,
    recurrence_info,
    spawn_next,
)
from app.services.taskdates import display_today, due_day
from app.services.tasks import (
    allocate_task_seq,
    apply_done_filter,
    assert_parent_one_level,
    create_task_record,
    reject_legacy_status,
)

router = APIRouter(tags=["tasks"])

# Что исполнитель вправе менять в СВОЕЙ задаче помимо роли в проекте.
# Назначение выдаёт ему viewer-членство (project_access.ensure_project_member),
# и без этого правила он не мог бы даже отметить задачу выполненной.
# `position` сюда НЕ входит: порядок остаётся редакторским, поэтому
# drag-n-drop доски (шлёт stage_id + position одним PATCH) под правило не подпадает.
ASSIGNEE_EDITABLE_FIELDS = frozenset({"done", "stage_id"})

# Ранжирование приоритета для ORDER BY (колонка — строковый enum).
PRIORITY_ORDER: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "urgent": 4}

TaskSortField = Literal["position", "due_at", "priority", "created_at", "title"]





# Алиасы старых имён: update_task/тесты зовут их отсюда.
_allocate_task_seq = allocate_task_seq
_assert_parent_one_level = assert_parent_one_level

_serialize = serialize_with_assignees


async def _serialize_one(
    db: AsyncSession,
    task: Task,
    *,
    rights_for: tuple[ProjectRole | None, Principal] | None = None,
) -> TaskResponse:
    """`rights_for=(role, principal)` — заполнить `can_complete`.

    Передаём только там, где роль уже посчитана и клиенту нужен контрол
    выполнения (get_task). Мутирующие ручки поле не заполняют сознательно:
    их ответ в кэш клиента не попадает.
    """
    by_task = await load_assignees(db, [task.id])
    assignees = by_task.get(task.id, [])
    data = _serialize(task, assignees)
    rules = await load_rules(db, [task.id])
    data.recurrence = recurrence_info(rules.get(task.id), today=display_today())
    if rights_for is not None:
        role, principal = rights_for
        data.can_complete = can_complete(role, principal.employee_id, assignees)
    return data


# ─── List & Create ──────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    project_id: UUID,
    include_archived: bool = Query(default=False),
    done: bool | None = Query(default=None),
    # LEGACY: неизвестный query FastAPI просто проигнорировал бы, и старый
    # бандл увидел бы НЕотфильтрованный список вместо ошибки (0044).
    status_: str | None = Query(default=None, alias="status"),
    assignee_id: UUID | None = Query(default=None, alias="assignee"),
    priority: TaskPriority | None = Query(default=None),
    label: UUID | None = Query(default=None),
    due_from: datetime | None = Query(default=None),
    due_to: datetime | None = Query(default=None),
    sort: TaskSortField = Query(default="position"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
    # keyword-only и последним: тесты зовут list_tasks позиционными kwargs.
    stage_id: UUID | None = Query(default=None),
) -> list[TaskResponse]:
    project, my_role = await require_project_role(db, project_id, principal)
    # В ЧУЖОМ личном проекте приглашённый видит только свои задачи: назначение
    # исполнителем выдаёт ему viewer-членство (project_access.ensure_project_member),
    # а оно открывало бы весь личный список.
    scope = personal_task_scope(project, principal)

    if sort == "priority":
        sort_col = case(PRIORITY_ORDER, value=Task.priority, else_=0)
    elif sort == "title":
        sort_col = func.lower(Task.title)
    else:
        sort_col = getattr(Task, sort)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()
    if sort == "due_at":
        sort_expr = sort_expr.nulls_last()

    # БЕЗ JOIN на исполнителей: он размножил бы строку задачи по их числу
    # (дубли карточек на доске, поехавшая сортировка). Исполнители едут
    # отдельным батч-запросом ниже.
    stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        # Тай-брейкер `seq` обязателен, и это не косметика. `position`
        # считается ВНУТРИ колонки (`stages.next_position`), поэтому в проекте
        # позиции массово совпадают: на проде у «Ввода/вывода сотрудников» 214
        # задач на 56 различных позиций. При сортировке по умолчанию
        # (`sort=position`) выражение вырождалось в `ORDER BY position,
        # position` — второго ключа не было вовсе, и порядок равных строк
        # Postgres вправе менять от запроса к запросу. Пока задачи
        # группировались по секциям, совпадений внутри блока было мало и это не
        # бросалось в глаза; в плоском списке список бы «плавал».
        .order_by(sort_expr, Task.position, Task.seq)
    )
    if scope is not None:
        stmt = stmt.where(scope)
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None))
    reject_legacy_status(status_)
    stmt = apply_done_filter(stmt, done)
    if assignee_id is not None:
        # Семантика: «сотрудник СРЕДИ исполнителей».
        stmt = stmt.where(assignee_exists(assignee_id))
    if stage_id is not None:
        stmt = stmt.where(Task.stage_id == stage_id)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if label is not None:
        stmt = stmt.where(
            select(TaskLabelAssignment.task_id)
            .where(
                TaskLabelAssignment.task_id == Task.id,
                TaskLabelAssignment.label_id == label,
            )
            .exists()
        )
    if due_from is not None:
        stmt = stmt.where(Task.due_at >= due_from)
    if due_to is not None:
        stmt = stmt.where(Task.due_at <= due_to)

    tasks = (await db.execute(stmt)).scalars().all()
    ids = [t.id for t in tasks]
    by_task = await load_assignees(db, ids)
    counts = await load_row_counts(db, ids)
    rules = await load_rules(db, ids)
    today = display_today()
    out: list[TaskResponse] = []
    for t in tasks:
        assignees = by_task.get(t.id, [])
        item = _serialize(t, assignees)
        item.recurrence = recurrence_info(rules.get(t.id), today=today)
        item.can_complete = can_complete(my_role, principal.employee_id, assignees)
        c = counts.get(t.id)
        if c is not None:
            item.comment_count = c.comments
            item.attachment_count = c.attachments
            item.blocker_count = c.blockers
        out.append(item)
    return out


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: UUID,
    body: TaskCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    await require_project_role(db, project_id, principal, allow=("owner", "editor"))
    # Доменная работа — в services/tasks.py: тот же путь использует импорт из
    # CSV (ему нельзя ходить через ручку из-за rate-limit).
    task = await create_task_record(db, principal=principal, project_id=project_id, body=body)
    await db.commit()
    await db.refresh(task)
    return await _serialize_one(db, task)


# ─── Single task ────────────────────────────────────────────────────────────


async def _fetch_task_with_role(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> tuple[Task, ProjectRole | None]:
    """Задача + роль вызывающего в её проекте (None — hub-admin-байпас)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    # Reuse the project visibility check (404 if not a project member and not admin).
    _project, role = await require_task_access(db, task, principal)
    return task, role


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    """Та же проверка без роли — её ждут 10 call-sites в других роутерах."""
    task, _role = await _fetch_task_with_role(db, task_id, principal)
    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task, role = await _fetch_task_with_role(db, task_id, principal)
    return await _serialize_one(db, task, rights_for=(role, principal))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    body: TaskUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    # «Я исполнитель?» — ДО гейта: иначе 403 прилетит раньше, чем мы узнаем про
    # назначение. Смешанный патч ({status, priority}) под правило не подпадает —
    # набор полей обязан целиком лежать в ASSIGNEE_EDITABLE_FIELDS.
    touched = set(body.model_fields_set)
    allow: tuple[ProjectRole, ...] = ("owner", "editor")
    if touched and touched <= ASSIGNEE_EDITABLE_FIELDS and await is_task_assignee(
        db, task.id, principal.employee_id
    ):
        allow = ("owner", "editor", "viewer")
    await require_task_access(db, task, principal, allow=allow)

    changes: dict[str, Any] = {}

    if body.title is not None and body.title != task.title:
        changes["title"] = {"old": task.title, "new": body.title}
        task.title = body.title

    if body.description is not None and body.description != task.description:
        changes["description"] = True  # not logging full body
        task.description = body.description

    # Nullable-поля различают «не пришло» (нет в model_fields_set — не трогаем)
    # и «пришёл явный null» (очистить значение).

    if body.priority is not None and body.priority != task.priority:
        changes["priority"] = {"old": task.priority, "new": body.priority}
        task.priority = body.priority

    if "due_at" in body.model_fields_set and body.due_at != task.due_at:
        changes["due_at"] = {
            "old": task.due_at.isoformat() if task.due_at else None,
            "new": body.due_at.isoformat() if body.due_at else None,
        }
        task.due_at = body.due_at

    if "start_at" in body.model_fields_set and body.start_at != task.start_at:
        changes["start_at"] = {
            "old": task.start_at.isoformat() if task.start_at else None,
            "new": body.start_at.isoformat() if body.start_at else None,
        }
        task.start_at = body.start_at

    actor_name_row = await db.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == principal.employee_id
        )
    )
    actor_rec = actor_name_row.first()
    actor_name = (actor_rec.full_name if actor_rec else None) or (
        actor_rec.email if actor_rec else "Кто-то"
    )

    # Replace-семантика: набор становится ровно тем, что прислали. None —
    # «исполнителей не трогать», [] — «снять всех» (в т.ч. легаси
    # `assignee_id: null` от старого бандла снимает ВСЕХ, а не одного).
    wanted = resolve_assignee_ids(body)
    if wanted is not None:
        diff = await set_task_assignees(
            db, task=task, employee_ids=wanted, actor_id=principal.employee_id
        )
        if diff.changed:
            await apply_assignee_side_effects(
                db,
                task=task,
                diff=diff,
                actor_id=principal.employee_id,
                actor_name=actor_name,
            )

    # Колонка доски и выполнение — независимые оси (0044). Перенос карточки
    # пишется в ленту, но людей не будит: на доске из пяти колонок пуш за
    # каждый шаг превратился бы в шум. Пуш остаётся за сменой «выполнена».
    clearing_stage = "stage_id" in body.model_fields_set and body.stage_id is None
    if clearing_stage and task.stage_id is not None:
        # Прочерк в поле «Статус» (0046): задача уходит с доски, оставаясь
        # в списке, календаре и поиске. Позицию не трогаем — она пригодится,
        # если статус вернут.
        previous = await db.get(ProjectStage, task.stage_id)
        task.stage_id = None
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="stage_changed",
            payload={
                "stage_from": previous.name if previous is not None else None,
                "stage_to": None,
            },
        )
    if body.stage_id is not None and body.stage_id != task.stage_id:
        target_stage = await get_stage_in_project(db, task.project_id, body.stage_id)
        previous_id = await set_stage(db, task, target_stage)
        # previous_id пуст, если статуса не было вовсе: `db.get` с None
        # не «не нашёл», а некорректный первичный ключ.
        previous = await db.get(ProjectStage, previous_id) if previous_id else None
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="stage_changed",
            payload={
                "stage_from": previous.name if previous is not None else None,
                "stage_to": target_stage.name,
            },
        )

    if body.done is not None and body.done != task.done:
        set_done(task, body.done)
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="done_changed",
            payload={"done": task.done},
        )
        watcher_rows = await db.execute(
            select(TaskWatcher.employee_id).where(
                TaskWatcher.task_id == task.id,
                TaskWatcher.employee_id != principal.employee_id,
            )
        )
        for (emp_id,) in watcher_rows.all():
            await notify_done_changed(
                db,
                task=task,
                done=task.done,
                actor_name=actor_name,
                recipient_id=emp_id,
            )
        if task.done:
            # Следующая копия повторяющейся задачи — в ЭТОЙ же транзакции:
            # закрытие и копия либо есть оба, либо нет ни одного. Правило
            # внутри забирается атомарно (`claim_rule`), поэтому снять галочку
            # и поставить снова второй копии не даст.
            await spawn_next(db, task=task, actor_id=principal.employee_id)

    if body.position is not None:
        # 3a stub — set as-is; rebalance / collision-handling lands with @dnd-kit in 3b.
        task.position = body.position

    if changes:
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="updated",
            payload=changes,
        )

    await db.commit()
    await db.refresh(task)
    return await _serialize_one(db, task)


# ─── Перенос в другой проект ────────────────────────────────────────────────
#
# Не поле в PATCH: у переезда своя цена (перенумерация, отвал меток и значений
# полей, отзыв публичной ссылки), и человек обязан увидеть её ДО нажатия.
# Отсюда две ручки на один расчёт — `services/task_move.py::plan_move`.


def _move_report(plan: MovePlan, task: Task) -> TaskMoveReport:
    return TaskMoveReport(
        project_id=plan.target.id,
        project_name=plan.target.name,
        new_key=plan.new_keys.get(task.id),
        subtasks=plan.subtasks,
        labels_kept=len(plan.labels_keep),
        labels_total=plan.labels_total,
        values_kept=len(plan.values_keep),
        values_total=plan.values_total,
        watchers_dropped=len(plan.watchers_drop),
        dependencies_dropped=plan.dependencies_drop,
        shares_revoked=plan.shares_revoke,
        target_public=plan.target_public,
    )


async def _move_context(
    db: AsyncSession,
    *,
    task_id: UUID,
    project_id: UUID,
    principal: Principal,
    lock: bool,
) -> tuple[Task, Project, Project]:
    """Задача, её проект и цель — с ролью редактора в ОБОИХ.

    Прав в источнике мало: без проверки цели задачу можно было бы затолкать в
    проект, которого не видишь.

    `lock=True` (запись) берёт строку задачи `FOR UPDATE`: два одновременных
    переноса в разные проекты иначе выдали бы два номера, задача осталась бы
    в проекте последнего, а первому ушёл бы отчёт про проект, где её нет.
    """
    task = await db.get(Task, task_id, with_for_update=lock)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    source, _ = await require_task_access(db, task, principal, allow=EDIT_ROLES)
    target, _ = await require_project_role(db, project_id, principal, allow=EDIT_ROLES)
    return task, source, target


@router.get("/tasks/{task_id}/move-preview", response_model=TaskMoveReport)
async def preview_task_move(
    task_id: UUID,
    project_id: UUID = Query(...),
    stage_id: UUID | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskMoveReport:
    """Что случится при переносе. НИЧЕГО не пишет — в том числе не выдаёт номер.

    Свой bucket: диалог дёргает предпросмотр на каждую смену цели, и в общем
    `task:write` (120/мин) перебор проектов упёрся бы в 429 на СЛЕДУЮЩЕЙ
    правке задачи.
    """
    await enforce_rate_limit(
        bucket="task:move-preview",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    task, source, target = await _move_context(
        db, task_id=task_id, project_id=project_id, principal=principal, lock=False
    )
    plan = await plan_move(
        db,
        task=task,
        source=source,
        target=target,
        principal=principal,
        stage_id=stage_id,
    )
    return _move_report(plan, task)


@router.post("/tasks/{task_id}/move", response_model=TaskMoveReport)
async def move_task(
    task_id: UUID,
    body: TaskMoveRequest,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskMoveReport:
    """Перенести задачу (и её подзадачи) в другой проект."""
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task, source, target = await _move_context(
        db, task_id=task_id, project_id=body.project_id, principal=principal, lock=True
    )
    plan = await plan_move(
        db,
        task=task,
        source=source,
        target=target,
        principal=principal,
        stage_id=body.stage_id,
    )
    await apply_move(db, plan=plan, principal=principal)
    await db.commit()
    return _move_report(plan, task)


# ─── Assignees (инкрементальный путь) ───────────────────────────────────────
#
# PATCH с полным списком — это last-writer-wins по всему набору: если двое
# правят состав одновременно, добавленный одним молча исчезает. С одним
# исполнителем такого класса ошибок не было, с набором он становится реальным,
# поэтому UI ходит сюда, а PATCH остаётся для легаси-`assignee_id` и bulk.


async def _task_for_edit(db: AsyncSession, task_id: UUID, principal: Principal) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal, allow=("owner", "editor"))
    return task


async def _actor_name(db: AsyncSession, employee_id: UUID) -> str:
    row = await db.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == employee_id
        )
    )
    rec = row.first()
    if rec is None:
        return "Кто-то"
    return rec.full_name or rec.email or "Кто-то"


@router.put("/tasks/{task_id}/recurrence", response_model=TaskResponse)
async def set_task_recurrence(
    task_id: UUID,
    body: TaskRecurrenceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Включить или сменить повтор задачи.

    Смена правила ПЕРЕ-ЯКОРИВАЕТ серию (`anchor` = текущий срок, `occurrence`
    сбрасывается): иначе «поменял день на неделю» дало бы дату из старой сетки.
    """
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task = await _task_for_edit(db, task_id, principal)
    if task.parent_task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Повтор ставится на задачу, а не на подзадачу",
        )
    if task.due_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="У задачи нет срока — повтор считается от него",
        )
    # Задача уже породила следующую: правило переехало туда, и второй потомок
    # физически запрещён (partial-UNIQUE). Отвечаем понятно, а не 500 из БД.
    child = (
        await db.execute(select(Task.seq).where(Task.recurrence_parent_id == task.id))
    ).first()
    if child is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Эта задача уже породила следующую — поставьте повтор на неё",
        )
    await db.execute(
        pg_insert(TaskRecurrence)
        .values(
            task_id=task.id,
            tenant_id=principal.tenant_id,
            freq=body.freq,
            step=body.step,
            anchor=due_day(task.due_at),
            occurrence=0,
            created_by=principal.employee_id,
        )
        .on_conflict_do_update(
            index_elements=["task_id"],
            set_={
                "freq": body.freq,
                "step": body.step,
                "anchor": due_day(task.due_at),
                "occurrence": 0,
            },
        )
    )
    await record_activity(
        db,
        tenant_id=principal.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="recurrence_set",
        payload={"rule": describe(body.freq, body.step)},
    )
    await db.commit()
    await db.refresh(task)
    return await _serialize_one(db, task)


@router.delete("/tasks/{task_id}/recurrence", response_model=TaskResponse)
async def clear_task_recurrence(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Выключить повтор. Идемпотентно: правила не было — не ошибка."""
    task = await _task_for_edit(db, task_id, principal)
    existed = await load_rule(db, task.id)
    if existed is not None:
        await claim_rule(db, task.id)
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="recurrence_cleared",
            payload={"rule": describe(existed.freq, existed.step)},
        )
        await db.commit()
        await db.refresh(task)
    return await _serialize_one(db, task)


@router.post("/tasks/{task_id}/assignees", response_model=TaskResponse)
async def add_task_assignee(
    task_id: UUID,
    body: TaskAssigneeAdd,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Добавить одного исполнителя. Идемпотентно (повтор — не ошибка)."""
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task = await _task_for_edit(db, task_id, principal)
    diff = await add_assignee(
        db, task=task, employee_id=body.employee_id, actor_id=principal.employee_id
    )
    if diff.changed:
        await apply_assignee_side_effects(
            db,
            task=task,
            diff=diff,
            actor_id=principal.employee_id,
            actor_name=await _actor_name(db, principal.employee_id),
        )
        await db.commit()
        await db.refresh(task)
    return await _serialize_one(db, task)


@router.delete("/tasks/{task_id}/assignees/{employee_id}", response_model=TaskResponse)
async def remove_task_assignee(
    task_id: UUID,
    employee_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Снять одного исполнителя. Идемпотентно.

    Подписку и членство в проекте НЕ снимает — сегодняшняя семантика.
    """
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task = await _task_for_edit(db, task_id, principal)
    diff = await remove_assignee(
        db, task=task, employee_id=employee_id, actor_id=principal.employee_id
    )
    if diff.changed:
        await apply_assignee_side_effects(
            db,
            task=task,
            diff=diff,
            actor_id=principal.employee_id,
            actor_name=await _actor_name(db, principal.employee_id),
        )
        await db.commit()
        await db.refresh(task)
    return await _serialize_one(db, task)


@router.post("/tasks/{task_id}/archive", response_model=TaskResponse)
async def archive_task(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(
        db, task, principal, allow=("owner", "editor")
    )
    if task.archived_at is None:
        task.archived_at = datetime.now(UTC)
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="archived",
        )
        await db.commit()
        await db.refresh(task)
    return await _serialize_one(db, task)


@router.post("/tasks/{task_id}/unarchive", response_model=TaskResponse)
async def unarchive_task(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(
        db, task, principal, allow=("owner", "editor")
    )
    if task.archived_at is not None:
        task.archived_at = None
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="unarchived",
        )
        await db.commit()
        await db.refresh(task)
    return await _serialize_one(db, task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Жёсткое удаление задачи. Корзины нет — это решение владельца.

    Право у владельца, редактора и hub-admin (26.08): гейт совпал с тем, что
    клиенту обещает `can_edit`, — кнопка удаления живёт в том же меню карточки,
    что и «В архив», и показывать её тому, кто получит 403, нельзя.

    Каскад БД уносит подзадачи (`tasks.parent_task_id` ondelete CASCADE),
    комментарии, вложения, наблюдателей, исполнителей, ленту, зависимости и
    значения кастом-полей. Сверх каскада ручка чистит ДВЕ вещи, которые БД не
    знает: файлы вложений на диске и уведомления, ведущие на эту задачу.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if not is_hub_admin(principal):
        await require_task_access(db, task, principal, allow=EDIT_ROLES)

    # Ключи блобов — ДО удаления и вместе с подзадачами: их вложения уедут тем
    # же каскадом, а файлы остались бы на диске навсегда.
    doomed = select(Task.id).where(
        (Task.id == task.id) | (Task.parent_task_id == task.id)
    )
    blob_keys = list(
        (
            await db.execute(
                select(TaskAttachment.storage_key).where(
                    TaskAttachment.task_id.in_(doomed)
                )
            )
        )
        .scalars()
        .all()
    )
    # Уведомление переживает задачу, а ссылка в нём ведёт на `?task={id}`
    # (`services/notify.py::_task_url`) — «Входящие» иначе остаются с живой
    # строкой, которая открывает пустую карточку.
    await db.execute(
        delete(Notification).where(Notification.url.like(f"%task={task.id}"))
    )
    await db.delete(task)
    await db.commit()

    # Файлы — ПОСЛЕ commit и в отдельном потоке (см. докстринг purge_blobs).
    if blob_keys:
        await asyncio.to_thread(purge_blobs, blob_keys)


# Keep TaskPriority alive — currently used only as a Field type in schemas;
# explicit re-export here is a hedge against accidental "unused import" linting.
_ = TaskPriority
