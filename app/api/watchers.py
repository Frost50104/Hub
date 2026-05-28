"""Task watchers API — toggle whether current user watches a task."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskWatcher
from app.schemas.watcher import WatcherResponse
from app.services.activity_writer import record_activity
from app.services.project_access import require_project_role

router = APIRouter(tags=["watchers"])


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_project_role(db, task.project_id, principal)
    return task


@router.get("/tasks/{task_id}/watchers", response_model=list[WatcherResponse])
async def list_watchers(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[WatcherResponse]:
    await _fetch_task_visible(db, task_id, principal)
    rows = await db.execute(
        select(
            TaskWatcher.employee_id,
            TaskWatcher.added_reason,
            TaskWatcher.added_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskWatcher.employee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(TaskWatcher.task_id == task_id)
        .order_by(TaskWatcher.added_at)
    )
    return [
        WatcherResponse(
            employee_id=r.employee_id,
            added_reason=r.added_reason,
            added_at=r.added_at,
            email=r.email,
            full_name=r.full_name,
        )
        for r in rows.all()
    ]


@router.post(
    "/tasks/{task_id}/watchers/me",
    response_model=WatcherResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_watching(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> WatcherResponse:
    task = await _fetch_task_visible(db, task_id, principal)
    await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task.id,
            employee_id=principal.employee_id,
            tenant_id=task.tenant_id,
            added_reason="manual",
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )
    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="watcher_added",
    )
    await db.commit()
    me_row = await db.execute(
        select(ShadowUser.email, ShadowUser.full_name).where(
            ShadowUser.employee_id == principal.employee_id
        )
    )
    me = me_row.first()
    row = await db.execute(
        select(TaskWatcher.added_reason, TaskWatcher.added_at).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == principal.employee_id,
        )
    )
    rec = row.first()
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать watcher",
        )
    return WatcherResponse(
        employee_id=principal.employee_id,
        added_reason=rec.added_reason,
        added_at=rec.added_at,
        email=me.email if me else None,
        full_name=me.full_name if me else None,
    )


@router.delete(
    "/tasks/{task_id}/watchers/me", status_code=status.HTTP_204_NO_CONTENT
)
async def leave_watching(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _fetch_task_visible(db, task_id, principal)
    result = await db.execute(
        delete(TaskWatcher).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == principal.employee_id,
        )
    )
    if (result.rowcount or 0) > 0:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="watcher_removed",
        )
    await db.commit()
