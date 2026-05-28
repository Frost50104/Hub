"""Read-only activity feed for a task."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskActivity
from app.schemas.activity import ActivityResponse
from app.services.project_access import require_project_role

router = APIRouter(tags=["activity"])


@router.get("/tasks/{task_id}/activity", response_model=list[ActivityResponse])
async def list_activity(
    task_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityResponse]:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_project_role(db, task.project_id, principal)

    rows = await db.execute(
        select(
            TaskActivity.id,
            TaskActivity.task_id,
            TaskActivity.actor_id,
            TaskActivity.kind,
            TaskActivity.payload,
            TaskActivity.created_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskActivity.actor_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(TaskActivity.task_id == task_id)
        .order_by(TaskActivity.created_at)
        .limit(limit)
    )
    return [
        ActivityResponse(
            id=r.id,
            task_id=r.task_id,
            actor_id=r.actor_id,
            kind=r.kind,
            payload=r.payload,
            created_at=r.created_at,
            actor_email=r.email,
            actor_full_name=r.full_name,
        )
        for r in rows.all()
    ]
