"""POST/DELETE task dependencies (Phase 4.3).

Adding `predecessor → successor`:
- both tasks must live in the same project (UI affordance keeps it that way)
- caller must be editor/owner on that project
- cycle detection runs in `dependency_cycle.would_create_cycle` before INSERT

ON CONFLICT: idempotent — re-adding the same edge is a no-op 201.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.dependency import TaskDependency
from app.models.task import Task
from app.schemas.dependency import TaskDependencyResponse
from app.services.dependency_cycle import would_create_cycle
from app.services.project_access import require_project_role

router = APIRouter(tags=["dependencies"])


@router.post(
    "/tasks/{successor_id}/dependencies/{predecessor_id}",
    response_model=TaskDependencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_dependency(
    successor_id: UUID,
    predecessor_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskDependencyResponse:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    if predecessor_id == successor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Задача не может зависеть от самой себя",
        )

    successor = await db.get(Task, successor_id)
    predecessor = await db.get(Task, predecessor_id)
    if successor is None or predecessor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    if successor.project_id != predecessor.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Зависимости только внутри одного проекта",
        )
    await require_project_role(
        db, successor.project_id, principal, allow=("owner", "editor")
    )

    if await would_create_cycle(
        db, predecessor_id=predecessor_id, successor_id=successor_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Эта связь создаст цикл в зависимостях",
        )

    await db.execute(
        pg_insert(TaskDependency)
        .values(
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            tenant_id=principal.tenant_id,
        )
        .on_conflict_do_nothing(
            index_elements=["predecessor_id", "successor_id"]
        )
    )
    await db.commit()
    dep = await db.get(TaskDependency, (predecessor_id, successor_id))
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить связь",
        )
    return TaskDependencyResponse.model_validate(dep)


@router.delete(
    "/tasks/{successor_id}/dependencies/{predecessor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_dependency(
    successor_id: UUID,
    predecessor_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    successor = await db.get(Task, successor_id)
    if successor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(
        db, successor.project_id, principal, allow=("owner", "editor")
    )
    dep = await db.get(TaskDependency, (predecessor_id, successor_id))
    if dep is not None:
        await db.delete(dep)
        await db.commit()
