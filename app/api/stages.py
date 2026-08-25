"""Колонки доски проекта.

- `GET /projects/{id}/stages` — любой участник; с `task_count` для «N из M».
- `POST/PATCH/DELETE` — owner/editor. Колонка — это только имя и позиция
  (0044): системного смысла у неё нет, состояние задачи живёт в `tasks.done`.
- `DELETE` требует `move_to`, если в колонке есть задачи; последнюю колонку
  проекта удалить нельзя (409) — задачам негде лежать.

Позиции непрерывные, сдвиги — как у секций (`SET CONSTRAINTS … DEFERRED`).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.stage import ProjectStage
from app.models.task import Task
from app.schemas.stage import StageCreate, StageResponse, StageUpdate
from app.services.project_access import require_project_role
from app.services.stages import (
    assert_not_last_stage,
    get_stage_in_project,
    list_stages,
)

router = APIRouter(tags=["stages"])

_DEFER = text("SET CONSTRAINTS uq_project_stages_project_position DEFERRED")


@router.get("/projects/{project_id}/stages", response_model=list[StageResponse])
async def list_project_stages(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[StageResponse]:
    await require_project_role(db, project_id, principal)
    stages = await list_stages(db, project_id)
    counts = await db.execute(
        select(Task.stage_id, func.count())
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            Task.parent_task_id.is_(None),
        )
        .group_by(Task.stage_id)
    )
    by_stage = {sid: int(n) for sid, n in counts.all()}
    out: list[StageResponse] = []
    for s in stages:
        item = StageResponse.model_validate(s)
        item.task_count = by_stage.get(s.id, 0)
        out.append(item)
    return out


@router.post(
    "/projects/{project_id}/stages",
    response_model=StageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_stage(
    project_id: UUID,
    body: StageCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StageResponse:
    await enforce_rate_limit(
        bucket="task:write", employee_id=str(principal.employee_id), limit=120, window_sec=60
    )
    await require_project_role(db, project_id, principal, allow=("owner", "editor"))
    await db.execute(_DEFER)
    max_row = await db.execute(
        select(func.coalesce(func.max(ProjectStage.position), -1)).where(
            ProjectStage.project_id == project_id
        )
    )
    max_pos = int(max_row.scalar_one())
    position = body.position if body.position is not None else max_pos + 1
    if position > max_pos + 1:
        position = max_pos + 1
    if position <= max_pos:
        await db.execute(
            update(ProjectStage)
            .where(ProjectStage.project_id == project_id, ProjectStage.position >= position)
            .values(position=ProjectStage.position + 1)
        )
    stage = ProjectStage(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        name=body.name.strip(),
        position=position,
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return StageResponse.model_validate(stage)


@router.patch("/stages/{stage_id}", response_model=StageResponse)
async def update_stage(
    stage_id: UUID,
    body: StageUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StageResponse:
    await enforce_rate_limit(
        bucket="task:write", employee_id=str(principal.employee_id), limit=120, window_sec=60
    )
    stage = await db.get(ProjectStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этап не найден")
    await require_project_role(db, stage.project_id, principal, allow=("owner", "editor"))

    if body.name is not None:
        stage.name = body.name.strip()

    if body.position is not None and body.position != stage.position:
        await db.execute(_DEFER)
        count_row = await db.execute(
            select(func.count())
            .select_from(ProjectStage)
            .where(ProjectStage.project_id == stage.project_id)
        )
        total = int(count_row.scalar_one())
        new_pos = max(0, min(body.position, total - 1))
        old_pos = stage.position
        if new_pos < old_pos:
            await db.execute(
                update(ProjectStage)
                .where(
                    ProjectStage.project_id == stage.project_id,
                    ProjectStage.position >= new_pos,
                    ProjectStage.position < old_pos,
                )
                .values(position=ProjectStage.position + 1)
            )
        else:
            await db.execute(
                update(ProjectStage)
                .where(
                    ProjectStage.project_id == stage.project_id,
                    ProjectStage.position > old_pos,
                    ProjectStage.position <= new_pos,
                )
                .values(position=ProjectStage.position - 1)
            )
        stage.position = new_pos

    await db.commit()
    # Задачи этапа правились пачкой: их ORM-объекты в этой сессии несут
    # expired updated_at (server onupdate) — expire_all, чтобы последующий
    # db.get в том же процессе (ассистент, тесты) перечитал строки.
    db.expire_all()
    await db.refresh(stage)
    return StageResponse.model_validate(stage)


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(
    stage_id: UUID,
    move_to: UUID | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await enforce_rate_limit(
        bucket="task:write", employee_id=str(principal.employee_id), limit=120, window_sec=60
    )
    stage = await db.get(ProjectStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этап не найден")
    await require_project_role(db, stage.project_id, principal, allow=("owner", "editor"))
    await assert_not_last_stage(db, stage)

    tasks = (await db.execute(select(Task).where(Task.stage_id == stage.id))).scalars().all()
    if tasks:
        if move_to is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="В этапе есть задачи — укажите, в какой этап их перенести (move_to)",
            )
        if move_to == stage.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя перенести в удаляемый этап"
            )
        target = await get_stage_in_project(db, stage.project_id, move_to)
        for t in tasks:
            # Только колонка: перенос при удалении не трогает состояние задачи.
            t.stage_id = target.id

    await db.execute(_DEFER)
    await db.delete(stage)
    await db.flush()
    await db.execute(
        update(ProjectStage)
        .where(
            ProjectStage.project_id == stage.project_id,
            ProjectStage.position > stage.position,
        )
        .values(position=ProjectStage.position - 1)
    )
    await db.commit()
    db.expire_all()
