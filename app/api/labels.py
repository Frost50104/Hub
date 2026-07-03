"""Labels API — per-project теги задач.

Permissions (по образцу custom_fields):
- GET labels / GET label-assignments → viewer+ on project
- POST/PATCH/DELETE label            → owner only (or hub:admin)
- PUT/DELETE task label              → editor+ (bucket task:write)

`GET /projects/{id}/label-assignments` — bulk-выдача всех назначений проекта
одним запросом (зеркало bulk custom-field values): чипы в List/Board без N+1.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.task import Task, TaskLabel, TaskLabelAssignment
from app.schemas.label import (
    LabelAssignmentResponse,
    LabelCreate,
    LabelResponse,
    LabelUpdate,
)
from app.services.activity_writer import record_activity
from app.services.project_access import require_project_role

router = APIRouter(tags=["labels"])


async def _assert_unique_name(
    db: AsyncSession, project_id: UUID, name: str, *, exclude_id: UUID | None = None
) -> None:
    stmt = select(TaskLabel.id).where(
        TaskLabel.project_id == project_id, TaskLabel.name == name
    )
    if exclude_id is not None:
        stmt = stmt.where(TaskLabel.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Метка «{name}» уже существует в этом проекте",
        )


# ─── Label definitions ──────────────────────────────────────────────────────


@router.get("/projects/{project_id}/labels", response_model=list[LabelResponse])
async def list_labels(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[LabelResponse]:
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(TaskLabel)
        .where(TaskLabel.project_id == project_id)
        .order_by(TaskLabel.name)
    )
    return [LabelResponse.model_validate(x) for x in rows.scalars().all()]


@router.post(
    "/projects/{project_id}/labels",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_label(
    project_id: UUID,
    body: LabelCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LabelResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))
    await _assert_unique_name(db, project_id, body.name)

    label = TaskLabel(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        name=body.name,
        color=body.color,
    )
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return LabelResponse.model_validate(label)


@router.patch(
    "/projects/{project_id}/labels/{label_id}", response_model=LabelResponse
)
async def update_label(
    project_id: UUID,
    label_id: UUID,
    body: LabelUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LabelResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))

    label = await db.get(TaskLabel, label_id)
    if label is None or label.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Метка не найдена"
        )
    if body.name is not None and body.name != label.name:
        await _assert_unique_name(db, project_id, body.name, exclude_id=label_id)
        label.name = body.name
    if body.color is not None:
        label.color = body.color
    await db.commit()
    await db.refresh(label)
    return LabelResponse.model_validate(label)


@router.delete(
    "/projects/{project_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_label(
    project_id: UUID,
    label_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_project_role(db, project_id, principal, allow=("owner",))

    label = await db.get(TaskLabel, label_id)
    if label is None or label.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Метка не найдена"
        )
    # Назначения уходят каскадом (FK ON DELETE CASCADE).
    await db.delete(label)
    await db.commit()


# ─── Bulk assignments (для чипов в List/Board без N+1) ─────────────────────


@router.get(
    "/projects/{project_id}/label-assignments",
    response_model=list[LabelAssignmentResponse],
)
async def list_label_assignments(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[LabelAssignmentResponse]:
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(TaskLabelAssignment.task_id, TaskLabelAssignment.label_id)
        .join(TaskLabel, TaskLabel.id == TaskLabelAssignment.label_id)
        .where(TaskLabel.project_id == project_id)
    )
    return [
        LabelAssignmentResponse(task_id=task_id, label_id=label_id)
        for task_id, label_id in rows.all()
    ]


# ─── Assign / unassign on a task ────────────────────────────────────────────


async def _load_task_and_label(
    db: AsyncSession, task_id: UUID, label_id: UUID, principal: Principal
) -> tuple[Task, TaskLabel]:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(db, task.project_id, principal, allow=("owner", "editor"))
    label = await db.get(TaskLabel, label_id)
    # Метка обязана принадлежать проекту задачи — иначе через смежный проект
    # того же tenant'а можно навесить чужую метку.
    if label is None or label.project_id != task.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Метка не найдена"
        )
    return task, label


@router.put(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def assign_label(
    task_id: UUID,
    label_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task, label = await _load_task_and_label(db, task_id, label_id, principal)

    # Идемпотентно: повторное назначение — no-op.
    result = await db.execute(
        pg_insert(TaskLabelAssignment)
        .values(task_id=task.id, label_id=label.id, tenant_id=task.tenant_id)
        .on_conflict_do_nothing(constraint="pk_task_label_assignments")
    )
    if result.rowcount:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="labeled",
            payload={"label_id": str(label.id), "name": label.name},
        )
    await db.commit()


@router.delete(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_label(
    task_id: UUID,
    label_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task, label = await _load_task_and_label(db, task_id, label_id, principal)

    result = await db.execute(
        delete(TaskLabelAssignment).where(
            TaskLabelAssignment.task_id == task.id,
            TaskLabelAssignment.label_id == label.id,
        )
    )
    if result.rowcount:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="unlabeled",
            payload={"label_id": str(label.id), "name": label.name},
        )
    await db.commit()
