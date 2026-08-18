"""Tasks API (Hub-MVP.3a). CRUD + status/section/assignee/due changes +
archive. Drag-reorder via PATCH `position` lands in 3b; watchers/comments
land in 3c.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.project import Project
from app.models.section import Section
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskLabelAssignment, TaskWatcher
from app.schemas.task import (
    TaskAssigneeAdd,
    TaskCreate,
    TaskPriority,
    TaskResponse,
    TaskStatus,
    TaskUpdate,
    resolve_assignee_ids,
)
from app.services.activity_writer import record_activity
from app.services.notify import notify_status_changed
from app.services.project_access import is_hub_admin, require_project_role
from app.services.task_assignees import (
    add_assignee,
    apply_assignee_side_effects,
    assert_assignees_in_tenant,
    assignee_exists,
    load_assignees,
    remove_assignee,
    serialize_with_assignees,
    set_task_assignees,
)
from app.services.task_watchers import ensure_watcher

router = APIRouter(tags=["tasks"])

# Ранжирование приоритета для ORDER BY (колонка — строковый enum).
PRIORITY_ORDER: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "urgent": 4}

TaskSortField = Literal["position", "due_at", "priority", "created_at", "title"]


async def _next_position(db: AsyncSession, project_id: UUID, status_: str) -> Decimal:
    """Append: next position = max(position in the same project/status) + 1."""
    row = await db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 1)).where(
            Task.project_id == project_id, Task.status == status_
        )
    )
    return Decimal(row.scalar_one())


async def _allocate_task_seq(db: AsyncSession, project_id: UUID) -> int:
    """Атомарная выдача номера задачи («KEY-42»).

    Row-lock строки проекта живёт до конца транзакции и сериализует
    конкурентные создания — retry не нужен, UNIQUE(project_id, seq) остаётся
    страховочной сеткой. Дыры в нумерации при rollback допустимы (как в Jira).
    Звать ПОСЛЕДНИМ перед Task(...), чтобы не держать лок при 400/404.
    """
    row = await db.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(next_task_seq=Project.next_task_seq + 1)
        .returning(Project.next_task_seq - 1)
    )
    return row.scalar_one()


_serialize = serialize_with_assignees


async def _serialize_one(db: AsyncSession, task: Task) -> TaskResponse:
    by_task = await load_assignees(db, [task.id])
    return _serialize(task, by_task.get(task.id, []))


async def _assert_section_in_project(
    db: AsyncSession, project_id: UUID, section_id: UUID | None
) -> None:
    if section_id is None:
        return
    row = await db.execute(
        select(Section.id).where(Section.id == section_id, Section.project_id == project_id)
    )
    if row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Секция не принадлежит этому проекту",
        )


async def _assert_parent_one_level(db: AsyncSession, parent_task_id: UUID | None) -> None:
    if parent_task_id is None:
        return
    parent = await db.get(Task, parent_task_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Родительская задача не найдена"
        )
    if parent.parent_task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подзадачи поддерживаются только одного уровня",
        )


# ─── List & Create ──────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    project_id: UUID,
    include_archived: bool = Query(default=False),
    status_: TaskStatus | None = Query(default=None, alias="status"),
    assignee_id: UUID | None = Query(default=None, alias="assignee"),
    section_id: UUID | None = Query(default=None),
    priority: TaskPriority | None = Query(default=None),
    label: UUID | None = Query(default=None),
    due_from: datetime | None = Query(default=None),
    due_to: datetime | None = Query(default=None),
    sort: TaskSortField = Query(default="position"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    await require_project_role(db, project_id, principal)

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
        # Вторичный ключ position — стабильный порядок при равных значениях.
        .order_by(sort_expr, Task.position)
    )
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None))
    if status_ is not None:
        stmt = stmt.where(Task.status == status_)
    if assignee_id is not None:
        # Семантика: «сотрудник СРЕДИ исполнителей».
        stmt = stmt.where(assignee_exists(assignee_id))
    if section_id is not None:
        stmt = stmt.where(Task.section_id == section_id)
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
    by_task = await load_assignees(db, [t.id for t in tasks])
    return [_serialize(t, by_task.get(t.id, [])) for t in tasks]


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
    await _assert_section_in_project(db, project_id, body.section_id)
    # Валидация ВСЕГО списка до любых записей и до _allocate_task_seq: тот
    # держит row-lock проекта до конца транзакции, а 404 на третьем
    # исполнителе не должен оставлять первых двух записанными.
    assignee_ids = resolve_assignee_ids(body) or []
    assignee_names = await assert_assignees_in_tenant(db, assignee_ids)
    await _assert_parent_one_level(db, body.parent_task_id)

    task = Task(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        section_id=body.section_id,
        parent_task_id=body.parent_task_id,
        title=body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        created_by=principal.employee_id,
        start_at=body.start_at,
        due_at=body.due_at,
        position=await _next_position(db, project_id, body.status),
        seq=await _allocate_task_seq(db, project_id),
    )
    if body.status == "done":
        task.completed_at = datetime.now(UTC)
    db.add(task)
    # Flush so the task INSERT actually hits Postgres before we record an
    # activity row that references task.id (FK on task_activity.task_id).
    # ORM's topological INSERT sort doesn't help here — record_activity uses
    # `insert()` directly, bypassing the unit-of-work ordering.
    await db.flush()
    # Auto-watchers per INTEGRATION.md §14: creator + assignee subscribe on
    # task creation. Reason is the *first* edge they joined through.
    await ensure_watcher(
        db,
        task_id=task.id,
        tenant_id=task.tenant_id,
        employee_id=principal.employee_id,
        reason="creator",
    )
    # Строго ПОСЛЕ flush(): FK task_assignees.task_id требует, чтобы строка
    # задачи уже была в Postgres.
    diff = await set_task_assignees(
        db,
        task=task,
        employee_ids=assignee_ids,
        actor_id=principal.employee_id,
        validated_names=assignee_names,
    )
    if diff.changed:
        # notify/record выключены: создание задачи с исполнителем и раньше не
        # слало уведомлений, а лента начинается с «created».
        await apply_assignee_side_effects(
            db,
            task=task,
            diff=diff,
            actor_id=principal.employee_id,
            actor_name="",
            notify=False,
            record=False,
        )
    await record_activity(
        db,
        tenant_id=principal.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="created",
        payload={
            "title": body.title,
            "status": body.status,
            "section_id": str(body.section_id) if body.section_id else None,
        },
    )
    await db.commit()
    await db.refresh(task)
    return await _serialize_one(db, task)


# ─── Single task ────────────────────────────────────────────────────────────


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    # Reuse the project visibility check (404 if not a project member and not admin).
    await require_project_role(db, task.project_id, principal)
    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await _fetch_task_visible(db, task_id, principal)
    return await _serialize_one(db, task)


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
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
    )

    changes: dict[str, Any] = {}

    if body.title is not None and body.title != task.title:
        changes["title"] = {"old": task.title, "new": body.title}
        task.title = body.title

    if body.description is not None and body.description != task.description:
        changes["description"] = True  # not logging full body
        task.description = body.description

    # Nullable-поля различают «не пришло» (нет в model_fields_set — не трогаем)
    # и «пришёл явный null» (очистить значение).
    if "section_id" in body.model_fields_set and body.section_id != task.section_id:
        if body.section_id is not None:
            await _assert_section_in_project(db, task.project_id, body.section_id)
        changes["section_id"] = {
            "old": str(task.section_id) if task.section_id else None,
            "new": str(body.section_id) if body.section_id else None,
        }
        task.section_id = body.section_id

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

    if body.status is not None and body.status != task.status:
        old_status = task.status
        task.status = body.status
        if body.status == "done":
            task.completed_at = datetime.now(UTC)
        elif old_status == "done":
            task.completed_at = None
        # When status changes, re-bucket position to the tail of the new column.
        task.position = await _next_position(db, task.project_id, body.status)
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="status_changed",
            payload={"old": old_status, "new": body.status},
        )
        # Notify watchers (except the actor) about the status change.
        watcher_rows = await db.execute(
            select(TaskWatcher.employee_id).where(
                TaskWatcher.task_id == task.id,
                TaskWatcher.employee_id != principal.employee_id,
            )
        )
        for (emp_id,) in watcher_rows.all():
            await notify_status_changed(
                db,
                task=task,
                new_status=body.status,
                actor_name=actor_name,
                recipient_id=emp_id,
            )

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
    await require_project_role(db, task.project_id, principal, allow=("owner", "editor"))
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
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
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
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
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
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    # Hard delete: owner only (admin bypasses via is_hub_admin).
    if not is_hub_admin(principal):
        await require_project_role(db, task.project_id, principal, allow=("owner",))
    await db.delete(task)
    await db.commit()


# Keep TaskPriority alive — currently used only as a Field type in schemas;
# explicit re-export here is a hedge against accidental "unused import" linting.
_ = TaskPriority
