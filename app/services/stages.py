"""Колонки доски + состояние задачи — единственная точка записи обоих.

Модель (0044): **колонка — это только имя**, которое задаёт пользователь
(«Идея», «Согласование», «Печать»), а состояние задачи — отдельная ось
`tasks.done` (выполнена или нет). Оси независимы: галочку ставят из любой
колонки, и карточка остаётся на месте.

Инварианты:
- у задачи ВСЕГДА есть колонка (`tasks.stage_id` NOT NULL) — новая задача без
  явного `stage_id` уходит в первую по позиции;
- у проекта всегда есть хотя бы одна колонка: удаление последней → 409;
- `done` и `completed_at` пишет только `set_done` (БД сторожит их связь
  CHECK-констрейнтом `ck_tasks_done_completed_at`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stage import ProjectStage
from app.models.task import Task

# Колонки нового проекта. Это стартовый набор, а не системный смысл: любую
# можно переименовать, удалить и добавить свои.
DEFAULT_STAGES: tuple[str, ...] = (
    "К выполнению",
    "В работе",
    "На проверке",
    "Готово",
)


async def create_default_stages(
    db: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> list[ProjectStage]:
    """Стартовые колонки нового проекта в той же транзакции, что и сам проект."""
    out: list[ProjectStage] = []
    for position, name in enumerate(DEFAULT_STAGES):
        stage = ProjectStage(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            position=position,
        )
        db.add(stage)
        out.append(stage)
    await db.flush()
    return out


async def list_stages(db: AsyncSession, project_id: UUID) -> list[ProjectStage]:
    rows = await db.execute(
        select(ProjectStage)
        .where(ProjectStage.project_id == project_id)
        .order_by(ProjectStage.position, ProjectStage.created_at)
    )
    return list(rows.scalars().all())


async def get_stage_in_project(
    db: AsyncSession, project_id: UUID, stage_id: UUID
) -> ProjectStage:
    """Колонка принадлежит проекту — иначе 400 (как `_assert_section_in_project`)."""
    stage = await db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этап не принадлежит этому проекту",
        )
    return stage


async def first_stage(db: AsyncSession, project_id: UUID) -> ProjectStage | None:
    """Первая по позиции колонка проекта — дом для задачи без явного этапа.

    None означает проект вообще без колонок: API такого не допускает (удаление
    последней → 409), но падать на этом нельзя — вызывающий отвечает 409.
    """
    row = await db.execute(
        select(ProjectStage)
        .where(ProjectStage.project_id == project_id)
        .order_by(ProjectStage.position, ProjectStage.created_at)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def require_stage(
    db: AsyncSession, project_id: UUID, stage_id: UUID | None
) -> ProjectStage:
    """Колонка для задачи: явная либо первая. 409, если колонок нет вовсе."""
    if stage_id is not None:
        return await get_stage_in_project(db, project_id, stage_id)
    stage = await first_stage(db, project_id)
    if stage is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="В проекте нет ни одной колонки — создайте её на доске",
        )
    return stage


async def next_position(
    db: AsyncSession, project_id: UUID, *, stage_id: UUID
) -> Decimal:
    """Append в хвост колонки."""
    row = await db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 1)).where(
            Task.project_id == project_id, Task.stage_id == stage_id
        )
    )
    return Decimal(row.scalar_one())


async def set_stage(db: AsyncSession, task: Task, stage: ProjectStage) -> UUID:
    """Перенести задачу в колонку: `stage_id` + позиция в хвост.

    Состояние задачи (`done`) НЕ трогаем — это независимая ось. Возвращает
    прежний `stage_id` (вызывающему он нужен для ленты и уведомлений);
    побочки (activity, watchers) — у вызывающего, ему известен актор.
    """
    previous = task.stage_id
    task.stage_id = stage.id
    task.position = await next_position(db, task.project_id, stage_id=stage.id)
    return previous


def set_done(task: Task, value: bool) -> bool:
    """Отметить задачу выполненной или вернуть в работу; вернуть прежнее.

    Единственная точка записи `done` + `completed_at`. Дата закрытия не
    переписывается повторным «выполнена» — семантика прежняя.
    """
    was = task.done
    if was == value:
        return was
    task.done = value
    task.completed_at = datetime.now(UTC) if value else None
    return was


async def assert_not_last_stage(db: AsyncSession, stage: ProjectStage) -> None:
    """У проекта остаётся хотя бы одна колонка — иначе задаче негде лежать."""
    row = await db.execute(
        select(func.count())
        .select_from(ProjectStage)
        .where(
            ProjectStage.project_id == stage.project_id,
            ProjectStage.id != stage.id,
        )
    )
    if int(row.scalar_one()) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Это единственная колонка проекта — задачам негде лежать",
        )
