"""Создание задачи — общий путь для ручки `POST /projects/{id}/tasks` и импорта из CSV.

Вынесено из `app/api/tasks.py`, потому что импорт НЕ может звать ручку: на
ней `enforce_rate_limit(task:write, 120/мин)` на сотрудника — 121-я строка
файла упала бы в 429. Здесь — только доменная работа: валидации, позиция,
номер «KEY-42» (`allocate_task_seq` — единственный источник `seq`), активность,
наблюдатель-создатель, исполнители. Права, rate-limit и commit — у вызывающего.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.section import Section
from app.models.task import Task
from app.schemas.task import TaskCreate, resolve_assignee_ids
from app.services.activity_writer import record_activity
from app.services.stages import next_position, resolve_stage, stage_for_status
from app.services.task_assignees import (
    apply_assignee_side_effects,
    assert_assignees_in_tenant,
    set_task_assignees,
)
from app.services.task_watchers import ensure_watcher


async def allocate_task_seq(db: AsyncSession, project_id: UUID) -> int:
    """Атомарная выдача номера задачи («KEY-42»).

    Row-lock строки проекта живёт до конца транзакции и сериализует
    конкурентные создания — retry не нужен, UNIQUE(project_id, seq) остаётся
    страховочной сеткой. Дыры в нумерации при rollback допустимы (как в Jira).
    Звать ПОСЛЕДНИМ перед Task(...), чтобы не держать лок при 400/404.
    """
    row = await db.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(next_task_seq=Project.next_task_seq + 1)
        .returning(Project.next_task_seq - 1)
    )
    return row.scalar_one()


async def assert_section_in_project(
    db: AsyncSession, project_id: UUID, section_id: UUID | None
) -> None:
    if section_id is None:
        return
    row = await db.execute(
        select(Section.id).where(Section.id == section_id, Section.project_id == project_id)
    )
    if row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Секция не принадлежит этому проекту",
        )


async def assert_parent_one_level(db: AsyncSession, parent_task_id: UUID | None) -> None:
    if parent_task_id is None:
        return
    parent = await db.get(Task, parent_task_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Родительская задача не найдена"
        )
    if parent.parent_task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подзадачи поддерживаются только одного уровня",
        )


async def create_task_record(
    db: AsyncSession, *, principal: Principal, project_id: UUID, body: TaskCreate
) -> Task:
    """Создать задачу БЕЗ commit'а. Вызывающий проверил права проекта.

    Порядок обязателен: все валидации — до `allocate_task_seq` (он держит
    row-lock проекта до конца транзакции; 404 на третьем исполнителе не должен
    оставлять лок и первых двух записанными); `flush()` — до activity и
    исполнителей (FK на tasks.id).
    """
    await assert_section_in_project(db, project_id, body.section_id)
    assignee_ids = resolve_assignee_ids(body) or []
    assignee_names = await assert_assignees_in_tenant(db, assignee_ids)
    await assert_parent_one_level(db, body.parent_task_id)
    # Этап: явный stage_id либо первый этап присланного статуса (legacy).
    # `status` у TaskCreate имеет дефолт «todo» — учитываем его только если
    # прислан явно, иначе stage_id=«Готово» конфликтовал бы с дефолтом.
    explicit_status = body.status if "status" in body.model_fields_set else None
    stage = await resolve_stage(
        db, project_id, stage_id=body.stage_id, system_status=explicit_status
    )
    if stage is None:
        stage = await stage_for_status(db, project_id, body.status)
    task_status = stage.system_status if stage is not None else body.status

    task = Task(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        section_id=body.section_id,
        stage_id=stage.id if stage is not None else None,
        parent_task_id=body.parent_task_id,
        title=body.title,
        description=body.description,
        status=task_status,
        priority=body.priority,
        created_by=principal.employee_id,
        start_at=body.start_at,
        due_at=body.due_at,
        position=await next_position(
            db,
            project_id,
            stage_id=stage.id if stage is not None else None,
            system_status=task_status,
        ),
        seq=await allocate_task_seq(db, project_id),
    )
    if task_status == "done":
        task.completed_at = datetime.now(UTC)
    db.add(task)
    # Flush so the task INSERT actually hits Postgres before we record an
    # activity row that references task.id (FK on task_activity.task_id).
    # ORM's topological INSERT sort doesn't help here — record_activity uses
    # `insert()` directly, bypassing the unit-of-work ordering.
    await db.flush()
    # Auto-watchers per INTEGRATION.md §14: creator + assignee subscribe on
    # task creation. Reason is the *first* edge they joined through.
    await ensure_watcher(
        db,
        task_id=task.id,
        tenant_id=task.tenant_id,
        employee_id=principal.employee_id,
        reason="creator",
    )
    # Строго ПОСЛЕ flush(): FK task_assignees.task_id требует, чтобы строка
    # задачи уже была в Postgres.
    diff = await set_task_assignees(
        db,
        task=task,
        employee_ids=assignee_ids,
        actor_id=principal.employee_id,
        validated_names=assignee_names,
    )
    if diff.changed:
        # notify/record выключены: создание задачи с исполнителем и раньше не
        # слало уведомлений, а лента начинается с «created».
        await apply_assignee_side_effects(
            db,
            task=task,
            diff=diff,
            actor_id=principal.employee_id,
            actor_name="",
            notify=False,
            record=False,
        )
    await record_activity(
        db,
        tenant_id=principal.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="created",
        payload={
            "title": body.title,
            "status": task_status,
            "section_id": str(body.section_id) if body.section_id else None,
            "stage_id": str(stage.id) if stage is not None else None,
        },
    )
    return task
