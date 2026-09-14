"""Повтор задач: правило-токен и порождение следующей копии.

Модель — «при выполнении» (решение владельца): копия рождается ТОЛЬКО когда
предыдущую отметили выполненной. Отсюда главное свойство: заброшенная серия
останавливается сама, хвост невыполненных дублей не копится в принципе — в
отличие от ночной джобы, которая штамповала бы 365 копий независимо ни от чего.

ИДЕМПОТЕНТНОСТЬ БЕЗ ФЛАГОВ. Правило — строка `task_recurrences`, и она же
токен: порождение начинается с `DELETE ... RETURNING`, после чего правило
вставляется уже для копии. Снять галочку и поставить снова нечего — токена на
исходной задаче больше нет. Гонку двух вкладок закрывает row-lock самого
DELETE: вторая транзакция дождётся первой и не увидит строки.

ПОРЯДОК ЗАХВАТА КРИТИЧЕН: claim ДО `allocate_task_seq`. Тот берёт row-lock
строки проекта до конца транзакции; при обратном порядке два закрытия в одном
проекте дают ABBA-дедлок.

Копия НЕ идёт через `create_task_record`. В нём три гейта, которые на штатных
данных уронили бы само закрытие задачи:
  * `assert_project_accepts_tasks` → 409 в архивном проекте, где правка задач
    разрешена сознательно;
  * `assert_assignees_in_tenant` → 404, если исполнителя уволили в auth, то есть
    ежедневную задачу с уволившимся коллегой стало бы невозможно закрыть;
  * правило личного пространства и creator-watcher считаются от `principal`,
    а не от автора исходной задачи.
Переиспользуем ровно два примитива: `allocate_task_seq` и `next_position`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_field import TaskCustomFieldValue
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee, TaskLabelAssignment, TaskRecurrence
from app.schemas.task import TaskRecurrenceInfo
from app.services.activity_writer import record_activity
from app.services.recurrence_dates import describe, next_occurrence
from app.services.stages import next_position
from app.services.task_watchers import ensure_watcher
from app.services.taskdates import display_today, due_day, due_noon_utc
from app.services.tasks import allocate_task_seq

log = structlog.get_logger("task_recurrence")


@dataclass(frozen=True)
class Rule:
    freq: str
    step: int
    anchor: date
    occurrence: int
    created_by: UUID | None


async def load_rule(db: AsyncSession, task_id: UUID) -> Rule | None:
    row = (
        await db.execute(
            select(
                TaskRecurrence.freq,
                TaskRecurrence.step,
                TaskRecurrence.anchor,
                TaskRecurrence.occurrence,
                TaskRecurrence.created_by,
            ).where(TaskRecurrence.task_id == task_id)
        )
    ).first()
    return Rule(*row) if row is not None else None


async def load_rules(db: AsyncSession, task_ids: Sequence[UUID]) -> dict[UUID, Rule]:
    """Батч для списков: N+1 на 1 300 задачах проекта недопустим."""
    if not task_ids:
        return {}
    rows = await db.execute(
        select(
            TaskRecurrence.task_id,
            TaskRecurrence.freq,
            TaskRecurrence.step,
            TaskRecurrence.anchor,
            TaskRecurrence.occurrence,
            TaskRecurrence.created_by,
        ).where(TaskRecurrence.task_id.in_(list(task_ids)))
    )
    return {row[0]: Rule(*row[1:]) for row in rows.all()}


def recurrence_info(rule: Rule | None, *, today: date) -> TaskRecurrenceInfo | None:
    """Правило → ответ клиенту, включая СЛЕДУЮЩУЮ дату.

    Дату считает сервер: второй реализации календарной арифметики на клиенте
    нет и не будет (тот же принцип, что у переноса задачи).
    """
    if rule is None:
        return None
    next_due, _ = next_occurrence(
        freq=rule.freq,
        step=rule.step,
        anchor=rule.anchor,
        occurrence=rule.occurrence,
        today=today,
    )
    return TaskRecurrenceInfo(
        freq=rule.freq,
        step=rule.step,
        anchor=rule.anchor,
        occurrence=rule.occurrence,
        next_due=next_due,
        text=describe(rule.freq, rule.step),
    )


async def claim_rule(db: AsyncSession, task_id: UUID) -> Rule | None:
    """Забрать правило у задачи — ровно одному вызывающему.

    `DELETE ... RETURNING` под row-lock: вторая параллельная транзакция ждёт
    коммита первой, после чего её WHERE не находит строки и возвращает None.
    Звать ДО `allocate_task_seq` (см. докстринг модуля про ABBA).
    """
    row = (
        await db.execute(
            delete(TaskRecurrence)
            .where(TaskRecurrence.task_id == task_id)
            .returning(
                TaskRecurrence.freq,
                TaskRecurrence.step,
                TaskRecurrence.anchor,
                TaskRecurrence.occurrence,
                TaskRecurrence.created_by,
            )
        )
    ).first()
    return Rule(*row) if row is not None else None


async def _copy_assignees(
    db: AsyncSession, *, src_id: UUID, dst_id: UUID
) -> list[UUID]:
    """Скопировать исполнителей, пропустив уволенных. Возвращает их id."""
    rows = await db.execute(
        select(
            TaskAssignee.employee_id,
            TaskAssignee.tenant_id,
            TaskAssignee.position,
            TaskAssignee.assigned_by,
        )
        .join(ShadowUser, ShadowUser.employee_id == TaskAssignee.employee_id)
        .where(TaskAssignee.task_id == src_id, ShadowUser.deleted_at.is_(None))
        .order_by(TaskAssignee.position)
    )
    copied: list[UUID] = []
    for employee_id, tenant_id, position, assigned_by in rows.all():
        await db.execute(
            pg_insert(TaskAssignee)
            .values(
                task_id=dst_id,
                employee_id=employee_id,
                tenant_id=tenant_id,
                position=position,
                # «Кто назначил» — исторический факт серии, а не действие
                # того, кто сейчас закрыл предыдущую задачу.
                assigned_by=assigned_by,
            )
            .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
        )
        copied.append(employee_id)
    return copied


async def _copy_labels_and_fields(db: AsyncSession, *, src_id: UUID, dst_id: UUID) -> None:
    labels = await db.execute(
        select(TaskLabelAssignment.label_id, TaskLabelAssignment.tenant_id).where(
            TaskLabelAssignment.task_id == src_id
        )
    )
    for label_id, tenant_id in labels.all():
        await db.execute(
            pg_insert(TaskLabelAssignment)
            .values(task_id=dst_id, label_id=label_id, tenant_id=tenant_id)
            .on_conflict_do_nothing(index_elements=["task_id", "label_id"])
        )
    values = await db.execute(
        select(
            TaskCustomFieldValue.field_id,
            TaskCustomFieldValue.tenant_id,
            TaskCustomFieldValue.value,
        ).where(TaskCustomFieldValue.task_id == src_id)
    )
    for field_id, tenant_id, value in values.all():
        await db.execute(
            pg_insert(TaskCustomFieldValue)
            .values(task_id=dst_id, field_id=field_id, tenant_id=tenant_id, value=value)
            .on_conflict_do_nothing(index_elements=["task_id", "field_id"])
        )


def _shifted(moment: datetime | None, shift: int) -> datetime | None:
    """Сдвиг `start_at` на ту же дельту в днях.

    `timedelta` на инстанте безопасен ровно потому, что display tz сейчас без
    перехода на летнее время; срок (`due_at`) так двигать нельзя — он идёт
    через `due_noon_utc(date)`.
    """
    return None if moment is None else moment + timedelta(days=shift)


async def _clone_task(
    db: AsyncSession,
    *,
    src: Task,
    shift: int,
    due: date | None,
    parent_id: UUID | None,
    recurrence_parent_id: UUID | None,
) -> Task:
    copy = Task(
        id=uuid4(),
        tenant_id=src.tenant_id,
        project_id=src.project_id,
        parent_task_id=parent_id,
        stage_id=src.stage_id,
        title=src.title,
        description=src.description,
        priority=src.priority,
        # Серия принадлежит тому, кто её завёл, а не тому, кто ставит галочки:
        # иначе «создано мной» в /me/stats распухает у исполнителя.
        created_by=src.created_by,
        start_at=_shifted(src.start_at, shift),
        due_at=due_noon_utc(due) if due is not None else None,
        seq=await allocate_task_seq(db, src.project_id),
        position=await next_position(db, src.project_id, stage_id=src.stage_id),
        recurrence_parent_id=recurrence_parent_id,
        done=False,
        completed_at=None,
        archived_at=None,
    )
    db.add(copy)
    await db.flush()
    assignees = await _copy_assignees(db, src_id=src.id, dst_id=copy.id)
    await _copy_labels_and_fields(db, src_id=src.id, dst_id=copy.id)
    # Наблюдателей переводим, а не копируем: `manual` — подписка на КОНКРЕТНУЮ
    # задачу, а не на бесконечную серию (отписываться пришлось бы каждый раз),
    # `mentioned` бессмыслен без скопированных комментариев.
    if copy.created_by is not None:
        await ensure_watcher(
            db,
            task_id=copy.id,
            tenant_id=copy.tenant_id,
            employee_id=copy.created_by,
            reason="creator",
        )
    for employee_id in assignees:
        await ensure_watcher(
            db,
            task_id=copy.id,
            tenant_id=copy.tenant_id,
            employee_id=employee_id,
            reason="assignee",
        )
    return copy


async def spawn_next(
    db: AsyncSession, *, task: Task, actor_id: UUID, today: date | None = None
) -> Task | None:
    """Создать следующую копию повторяющейся задачи. Без commit'а.

    Возвращает копию или None — «повторять нечего» и «серия остановлена» для
    вызывающего одинаковы: закрытие задачи не должно зависеть от повтора.
    """
    project = await db.get(Project, task.project_id)
    stop_reason: str | None = None
    if task.archived_at is not None:
        stop_reason = "task_archived"
    elif project is not None and project.archived_at is not None:
        # Гейт создания задач (`assert_project_accepts_tasks`) отвечает 409, а
        # правка задач в архивном проекте разрешена сознательно — значит копию
        # не делаем, но закрытие обязано пройти.
        stop_reason = "project_archived"

    rule = await claim_rule(db, task.id)
    if rule is None:
        return None
    if stop_reason is not None:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=actor_id,
            kind="recurrence_stopped",
            payload={"reason": stop_reason},
        )
        log.info("recurrence.stopped", task_id=str(task.id), reason=stop_reason)
        return None

    base = due_day(task.due_at) if task.due_at is not None else rule.anchor
    due, step_no = next_occurrence(
        freq=rule.freq,
        step=rule.step,
        anchor=rule.anchor,
        occurrence=rule.occurrence,
        today=today or display_today(),
    )
    shift = (due - base).days

    copy = await _clone_task(
        db,
        src=task,
        shift=shift,
        due=due,
        parent_id=None,
        recurrence_parent_id=task.id,
    )

    subtasks = (
        await db.execute(
            select(Task)
            .where(Task.parent_task_id == task.id, Task.archived_at.is_(None))
            .order_by(Task.position, Task.seq)
        )
    ).scalars().all()
    for sub in subtasks:
        sub_due = due_day(sub.due_at) + timedelta(days=shift) if sub.due_at is not None else None
        await _clone_task(
            db,
            src=sub,
            shift=shift,
            due=sub_due,
            parent_id=copy.id,
            recurrence_parent_id=None,
        )

    await db.execute(
        insert(TaskRecurrence).values(
            task_id=copy.id,
            tenant_id=task.tenant_id,
            freq=rule.freq,
            step=rule.step,
            anchor=rule.anchor,
            occurrence=step_no,
            created_by=rule.created_by,
        )
    )

    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=actor_id,
        kind="recurrence_spawned",
        payload={"task_id": str(copy.id), "seq": copy.seq, "rule": describe(rule.freq, rule.step)},
    )
    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=copy.id,
        actor_id=actor_id,
        kind="recurrence_created",
        payload={"task_id": str(task.id), "seq": task.seq},
    )
    log.info(
        "recurrence.spawned",
        source_id=str(task.id),
        task_id=str(copy.id),
        freq=rule.freq,
        step=rule.step,
    )
    return copy
