"""Tasks API (Hub-MVP.3a). CRUD + status/section/assignee/due changes +
archive. Drag-reorder via PATCH `position` lands in 3b; watchers/comments
land in 3c.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.section import Section
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskWatcher
from app.schemas.task import (
    AssigneeBrief,
    TaskCreate,
    TaskPriority,
    TaskResponse,
    TaskStatus,
    TaskUpdate,
)
from app.services.activity_writer import record_activity
from app.services.notify import notify_assigned, notify_status_changed
from app.services.project_access import is_hub_admin, require_project_role

router = APIRouter(tags=["tasks"])


async def _ensure_watcher(
    db: AsyncSession,
    *,
    task_id: UUID,
    tenant_id: UUID,
    employee_id: UUID,
    reason: str,
) -> None:
    """Idempotent watcher add — ON CONFLICT DO NOTHING.

    Doesn't upgrade the reason (creator stays creator even if also assigned);
    the original reason is more informative for activity rendering.
    """
    await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task_id,
            employee_id=employee_id,
            tenant_id=tenant_id,
            added_reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )


async def _next_position(db: AsyncSession, project_id: UUID, status_: str) -> Decimal:
    """Append: next position = max(position in the same project/status) + 1."""
    row = await db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 1)).where(
            Task.project_id == project_id, Task.status == status_
        )
    )
    return Decimal(row.scalar_one())


async def _fetch_assignee(
    db: AsyncSession, employee_id: UUID | None
) -> AssigneeBrief | None:
    if employee_id is None:
        return None
    row = await db.execute(
        select(ShadowUser.employee_id, ShadowUser.email, ShadowUser.full_name).where(
            ShadowUser.employee_id == employee_id, ShadowUser.deleted_at.is_(None)
        )
    )
    rec = row.first()
    if rec is None:
        return None
    return AssigneeBrief(employee_id=rec.employee_id, email=rec.email, full_name=rec.full_name)


def _serialize(task: Task, assignee: AssigneeBrief | None) -> TaskResponse:
    data = TaskResponse.model_validate(task)
    data.assignee = assignee
    return data


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


async def _assert_assignee_in_tenant(
    db: AsyncSession, employee_id: UUID | None
) -> None:
    """Only employees that have logged into Hub (= present in shadow_users)
    can be assignees. Filtering by tenant happens via RLS on shadow_users."""
    if employee_id is None:
        return
    target = await db.get(ShadowUser, employee_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исполнитель не найден в Hub. Попросите его зайти на hub.signaris.ru.",
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
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    await require_project_role(db, project_id, principal)

    stmt = (
        select(Task, ShadowUser.email, ShadowUser.full_name)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == Task.assignee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Task.project_id == project_id)
        .order_by(Task.position)
    )
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None))
    if status_ is not None:
        stmt = stmt.where(Task.status == status_)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if section_id is not None:
        stmt = stmt.where(Task.section_id == section_id)

    out: list[TaskResponse] = []
    for task, email, full_name in (await db.execute(stmt)).all():
        assignee = (
            AssigneeBrief(employee_id=task.assignee_id, email=email, full_name=full_name)
            if task.assignee_id
            else None
        )
        out.append(_serialize(task, assignee))
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
    await _assert_section_in_project(db, project_id, body.section_id)
    await _assert_assignee_in_tenant(db, body.assignee_id)
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
        assignee_id=body.assignee_id,
        created_by=principal.employee_id,
        start_at=body.start_at,
        due_at=body.due_at,
        position=await _next_position(db, project_id, body.status),
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
    await _ensure_watcher(
        db,
        task_id=task.id,
        tenant_id=task.tenant_id,
        employee_id=principal.employee_id,
        reason="creator",
    )
    if body.assignee_id is not None and body.assignee_id != principal.employee_id:
        await _ensure_watcher(
            db,
            task_id=task.id,
            tenant_id=task.tenant_id,
            employee_id=body.assignee_id,
            reason="assignee",
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
    return _serialize(task, await _fetch_assignee(db, task.assignee_id))


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
    return _serialize(task, await _fetch_assignee(db, task.assignee_id))


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

    if "assignee_id" in body.model_fields_set and body.assignee_id != task.assignee_id:
        old_assignee = task.assignee_id
        if body.assignee_id is not None:
            await _assert_assignee_in_tenant(db, body.assignee_id)
        task.assignee_id = body.assignee_id
        if body.assignee_id is not None:
            # New assignee auto-subscribes (no-op if already a watcher).
            # Снятие исполнителя подписку НЕ снимает — он остаётся watcher'ом.
            await _ensure_watcher(
                db,
                task_id=task.id,
                tenant_id=task.tenant_id,
                employee_id=body.assignee_id,
                reason="assignee",
            )
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="assigned",
            payload={
                "old": str(old_assignee) if old_assignee else None,
                "new": str(body.assignee_id) if body.assignee_id else None,
            },
        )
        # Notify the new assignee (unless they assigned themselves).
        if body.assignee_id is not None and body.assignee_id != principal.employee_id:
            await notify_assigned(
                db,
                task=task,
                assignee_id=body.assignee_id,
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
    return _serialize(task, await _fetch_assignee(db, task.assignee_id))


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
    return _serialize(task, await _fetch_assignee(db, task.assignee_id))


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
    return _serialize(task, await _fetch_assignee(db, task.assignee_id))


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
