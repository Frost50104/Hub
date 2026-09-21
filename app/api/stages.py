"""Колонки доски проекта.

- `GET /projects/{id}/stages` — любой участник; с `task_count` для «N из M».
- `POST/PATCH/DELETE` — owner/editor. Колонка — это только имя и позиция
  (0044): системного смысла у неё нет, состояние задачи живёт в `tasks.done`.
- `DELETE` с задачами в колонке требует выбора: `move_to` — перенести их в
  другую колонку, `detach=true` — оставить без колонки (легально с 0046). Без
  того и другого — 409: молча снять колонку у пачки задач нельзя. Удалить можно
  ЛЮБУЮ колонку, включая последнюю: проект без колонок — штатное состояние
  (новый проект рождается именно таким).

Позиции непрерывные, сдвиги — как у секций (`SET CONSTRAINTS … DEFERRED`).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db_template_page, require_auth
from app.models.stage import ProjectStage
from app.models.task import Task
from app.schemas.stage import StageCreate, StageResponse, StageUpdate
from app.services.personal_projects import is_foreign_personal
from app.services.project_access import open_template_if_hidden, require_project_role
from app.services.stages import get_stage_in_project, list_stages

router = APIRouter(tags=["stages"])

_DEFER = text("SET CONSTRAINTS uq_project_stages_project_position DEFERRED")


@router.get("/projects/{project_id}/stages", response_model=list[StageResponse])
async def list_project_stages(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> list[StageResponse]:
    project, _role = await require_project_role(db, project_id, principal)
    # Гостю ЧУЖОГО личного — пусто: в ответе ещё и счётчики задач по колонкам,
    # то есть прямой пересчёт чужого инбокса.
    if is_foreign_personal(project, principal):
        return []
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
    db: AsyncSession = Depends(get_db_template_page),
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
    db: AsyncSession = Depends(get_db_template_page),
) -> StageResponse:
    await enforce_rate_limit(
        bucket="task:write", employee_id=str(principal.employee_id), limit=120, window_sec=60
    )
    stage = await db.get(ProjectStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этап не найден")
    # Колонка — дочерний объект: id шаблона в пути нет, открываем явно.
    await open_template_if_hidden(db, principal, project_id=stage.project_id, mode="edit")
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
    detach: bool = Query(
        default=False,
        description="Оставить задачи колонки без колонки вместо переноса",
    ),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db_template_page),
) -> None:
    await enforce_rate_limit(
        bucket="task:write", employee_id=str(principal.employee_id), limit=120, window_sec=60
    )
    stage = await db.get(ProjectStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этап не найден")
    # Колонка — дочерний объект: id шаблона в пути нет, открываем явно.
    await open_template_if_hidden(db, principal, project_id=stage.project_id, mode="edit")
    await require_project_role(db, stage.project_id, principal, allow=("owner", "editor"))
    # Проверки «это последняя колонка» здесь больше нет: проект без колонок —
    # штатное состояние, и создав первую колонку по ошибке, из него надо уметь
    # выйти. Судьбу задач по-прежнему выбирает человек, а не сервер.

    tasks = (await db.execute(select(Task).where(Task.stage_id == stage.id))).scalars().all()
    if tasks:
        # `is not True`, а не `not detach`: ручку зовут напрямую тесты и
        # джобы, а нерезолвнутый FastAPI-дефолт `Query(False)` истинен —
        # и защита от молчаливого снятия колонки просто не сработала бы.
        if move_to is None and detach is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "В колонке есть задачи — перенесите их в другую колонку "
                    "(move_to) или оставьте без колонки (detach)"
                ),
            )
        if move_to is not None and move_to == stage.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя перенести в удаляемый этап"
            )
        # `move_to` сильнее `detach`: явный адрес переноса — более конкретное
        # намерение, чем «оставить без колонки».
        target = (
            await get_stage_in_project(db, stage.project_id, move_to)
            if move_to is not None
            else None
        )
        for t in tasks:
            # Только колонка: удаление не трогает состояние задачи (`done`).
            t.stage_id = target.id if target else None

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
