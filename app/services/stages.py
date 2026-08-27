"""Колонки доски + состояние задачи — единственная точка записи обоих.

Модель (0044): **колонка — это только имя**, которое задаёт пользователь
(«Идея», «Согласование», «Печать»), а состояние задачи — отдельная ось
`tasks.done` (выполнена или нет). Оси независимы: галочку ставят из любой
колонки, и карточка остаётся на месте.

Инварианты:
- **колонок у проекта может не быть вовсе.** Новый проект рождается пустым:
  четыре стартовые колонки навязывали раскладку, которую никто не выбирал.
  Пока колонок нет, задача заводится без колонки (`stage_id IS NULL`, 0046) —
  она есть в списке, календаре и поиске, но не на доске. Отсюда же следует, что
  удалить можно ЛЮБУЮ колонку, включая последнюю;
- новая задача с колонками в проекте, но без явного `stage_id`, уходит в первую
  по позиции. Явный `stage_id` проверяется на принадлежность проекту;
- `done` и `completed_at` пишет только `set_done` (БД сторожит их связь
  CHECK-констрейнтом `ck_tasks_done_completed_at`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stage import ProjectStage
from app.models.task import Task


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

    None означает проект без колонок — штатное состояние нового проекта, а не
    поломка: задача просто заводится без колонки.
    """
    row = await db.execute(
        select(ProjectStage)
        .where(ProjectStage.project_id == project_id)
        .order_by(ProjectStage.position, ProjectStage.created_at)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def default_stage_for(
    db: AsyncSession, project_id: UUID, stage_id: UUID | None
) -> ProjectStage | None:
    """Колонка для новой задачи: явная — всегда, без явной — первая ИЛИ никакой.

    `None` означает «в проекте нет колонок» и это НЕ ошибка: задача без колонки
    легальна с 0046, а проект теперь рождается пустым. Раньше здесь был 409
    «создайте её на доске» — он опирался на снятый инвариант «≥1 колонка» и
    ронял бы создание задачи в каждом новом проекте.
    """
    if stage_id is not None:
        return await get_stage_in_project(db, project_id, stage_id)
    return await first_stage(db, project_id)


async def next_position(
    db: AsyncSession, project_id: UUID, *, stage_id: UUID | None
) -> Decimal:
    """Append в хвост колонки; `stage_id=None` — в хвост задач без статуса.

    Своя очередь у «без статуса» нужна, чтобы порядок в списке был устойчивым:
    общий `max(position)+1` по проекту дал бы всем таким задачам единицу.
    """
    same_stage = (
        Task.stage_id.is_(None) if stage_id is None else Task.stage_id == stage_id
    )
    row = await db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 1)).where(
            Task.project_id == project_id, same_stage
        )
    )
    return Decimal(row.scalar_one())


async def set_stage(db: AsyncSession, task: Task, stage: ProjectStage) -> UUID | None:
    """Перенести задачу в колонку: `stage_id` + позиция в хвост.

    Состояние задачи (`done`) НЕ трогаем — это независимая ось. Возвращает
    прежний `stage_id` — `None`, если задача была без статуса (0046);
    вызывающему он нужен для ленты, побочки на нём.
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
