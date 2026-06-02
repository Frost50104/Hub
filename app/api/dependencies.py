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
from pydantic import BaseModel, ConfigDict
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.dependency import TaskDependency
from app.models.task import Task
from app.schemas.dependency import TaskDependencyResponse
from app.services.dependency_cycle import would_create_cycle
from app.services.project_access import require_project_role

router = APIRouter(tags=["dependencies"])


class DependencyPeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str


class TaskDependenciesResponse(BaseModel):
    predecessors: list[DependencyPeer]
    successors: list[DependencyPeer]


@router.get(
    "/tasks/{task_id}/dependencies", response_model=TaskDependenciesResponse
)
async def list_dependencies(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskDependenciesResponse:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(db, task.project_id, principal)

    edge_rows = await db.execute(
        select(TaskDependency).where(
            or_(
                TaskDependency.predecessor_id == task_id,
                TaskDependency.successor_id == task_id,
            )
        )
    )
    edges = list(edge_rows.scalars().all())
    peer_ids = {
        edge.predecessor_id if edge.successor_id == task_id else edge.successor_id
        for edge in edges
    }
    if not peer_ids:
        return TaskDependenciesResponse(predecessors=[], successors=[])

    peer_rows = await db.execute(
        select(Task.id, Task.title, Task.status).where(Task.id.in_(peer_ids))
    )
    peers = {
        row.id: DependencyPeer(id=row.id, title=row.title, status=row.status)
        for row in peer_rows.all()
    }
    predecessors = [
        peers[edge.predecessor_id]
        for edge in edges
        if edge.successor_id == task_id and edge.predecessor_id in peers
    ]
    successors = [
        peers[edge.successor_id]
        for edge in edges
        if edge.predecessor_id == task_id and edge.successor_id in peers
    ]
    return TaskDependenciesResponse(
        predecessors=predecessors, successors=successors
    )


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
