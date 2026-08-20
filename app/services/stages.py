"""Этапы проекта — единственная точка записи `tasks.stage_id` + зеркала `tasks.status`.

Инварианты (CLAUDE.md):
- `tasks.status` == `stage.system_status` всегда; пишется ТОЛЬКО здесь
  (`set_stage`), ручки и ассистент ходят через этот модуль.
- У проекта ≥1 этап на КАЖДЫЙ системный статус: иначе «закрыть задачу» и
  «создать задачу» не знают куда. Удаление последнего → 409.
- Legacy-вход `status` (старые бандлы, ассистент, тесты) резолвится в первый
  по позиции этап этого статуса.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stage import SYSTEM_STATUSES, ProjectStage
from app.models.task import Task

# Имена по умолчанию = STATUS_LABEL_RU: контракт «Готово» в ответах ассистента
# и тестах не меняется; пользователь переименует под себя («Проверка ТУ»).
DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("К выполнению", "todo"),
    ("В работе", "in_progress"),
    ("На проверке", "in_review"),
    ("Готово", "done"),
)


async def create_default_stages(
    db: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> list[ProjectStage]:
    """Четыре этапа нового проекта в той же транзакции, что и сам проект."""
    out: list[ProjectStage] = []
    for position, (name, system_status) in enumerate(DEFAULT_STAGES):
        stage = ProjectStage(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            system_status=system_status,
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
    """Этап принадлежит проекту — иначе 400 (как `_assert_section_in_project`)."""
    stage = await db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этап не принадлежит этому проекту",
        )
    return stage


async def stage_for_status(
    db: AsyncSession, project_id: UUID, system_status: str
) -> ProjectStage | None:
    """Первый по позиции этап системного статуса. None — у проекта ещё нет
    этапов (проект создан до 0040 и не добрался до backfill — не должно быть,
    но падать из-за этого нельзя)."""
    row = await db.execute(
        select(ProjectStage)
        .where(
            ProjectStage.project_id == project_id,
            ProjectStage.system_status == system_status,
        )
        .order_by(ProjectStage.position)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def resolve_stage(
    db: AsyncSession,
    project_id: UUID,
    *,
    stage_id: UUID | None,
    system_status: str | None,
) -> ProjectStage | None:
    """Свести два входа к одному этапу.

    `stage_id` побеждает; `status` — legacy-путь (старые бандлы, ассистент,
    тесты). Оба и не согласованы → 422: два источника истины в одном запросе.
    """
    if stage_id is not None:
        stage = await get_stage_in_project(db, project_id, stage_id)
        if system_status is not None and system_status != stage.system_status:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stage_id и status противоречат друг другу",
            )
        return stage
    if system_status is not None:
        return await stage_for_status(db, project_id, system_status)
    return None


async def next_position(
    db: AsyncSession, project_id: UUID, *, stage_id: UUID | None, system_status: str
) -> Decimal:
    """Append в хвост колонки. Бакет — этап (колонка доски); у задач без
    этапа (окно деплоя) — статус, как раньше."""
    cond = Task.stage_id == stage_id if stage_id is not None else Task.status == system_status
    row = await db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 1)).where(
            Task.project_id == project_id, cond
        )
    )
    return Decimal(row.scalar_one())


def apply_stage(task: Task, stage: ProjectStage | None, *, system_status: str) -> str:
    """Проставить этап и зеркало статуса БЕЗ побочек; вернуть старый статус.

    completed_at — по факту перехода в/из `done` (иммутабельная семантика
    сохранена: повторный done не сбрасывает дату).
    """
    old = task.status
    task.stage_id = stage.id if stage is not None else task.stage_id
    task.status = system_status
    if system_status == "done" and old != "done":
        task.completed_at = datetime.now(UTC)
    elif system_status != "done" and old == "done":
        task.completed_at = None
    return old


async def set_stage(db: AsyncSession, task: Task, stage: ProjectStage) -> str:
    """Перевести задачу в этап: stage_id + status + completed_at + позиция в
    хвост новой колонки. Возвращает старый статус (для activity/уведомлений).
    Побочки (activity, watchers) — у вызывающего: ему известен актор."""
    old = apply_stage(task, stage, system_status=stage.system_status)
    task.position = await next_position(
        db, task.project_id, stage_id=stage.id, system_status=stage.system_status
    )
    return old


async def assert_not_last_of_status(
    db: AsyncSession, stage: ProjectStage, *, new_status: str | None = None
) -> None:
    """≥1 этап на каждый системный статус. Вызывается перед удалением этапа
    или сменой его system_status."""
    if new_status is not None and new_status == stage.system_status:
        return
    row = await db.execute(
        select(func.count())
        .select_from(ProjectStage)
        .where(
            ProjectStage.project_id == stage.project_id,
            ProjectStage.system_status == stage.system_status,
            ProjectStage.id != stage.id,
        )
    )
    if int(row.scalar_one()) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Это единственный этап статуса «{stage.system_status}» — у проекта "
                "должен остаться хотя бы один этап на каждый системный статус"
            ),
        )


def assert_system_status(value: str) -> None:
    if value not in SYSTEM_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Неизвестный системный статус",
        )
