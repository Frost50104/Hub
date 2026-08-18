"""Исполнители задачи — единственный писатель `task_assignees` (0034).

ИНВАРИАНТЫ, которые держит этот модуль:

1. `task_assignees` — ЕДИНСТВЕННОЕ место, где живут исполнители. Колонки-зеркала
   `tasks.assignee_id` больше нет (удалена ревизией 0036): она требовала
   синхронной записи при каждом изменении набора и разъезжалась на параллельных
   запросах — см. docs/TECH_DEBT.md, «ОС 17.08».
2. `tenant_id` берётся из `task.tenant_id`, НИКОГДА из principal — расхождение
   источников уже давало дыру 0011 в `task_label_assignments`.
3. Валидация всего списка идёт ДО любых записей: 404 на третьем исполнителе не
   должен оставлять первых двух записанными.
4. В списочных запросах `task_assignees` допустим ТОЛЬКО как EXISTS (фильтр)
   или отдельным батч-запросом (отображение) — наивный JOIN размножит строку
   задачи по числу исполнителей. Единственное исключение — stats._workload,
   где фан-аут намеренный.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee, TaskWatcher
from app.schemas.task import MAX_ASSIGNEES, AssigneeBrief, TaskResponse, dedupe
from app.services.activity_writer import record_activity
from app.services.notify import notify_assigned
from app.services.project_access import ensure_project_member
from app.services.task_watchers import ensure_watcher

# Чанк для in_(): число задач в списке проекта ничем не ограничено.
_CHUNK = 1000


@dataclass(frozen=True)
class AssigneeDiff:
    """Результат применения набора исполнителей."""

    final: list[UUID]
    added: list[UUID]
    removed: list[UUID]
    added_names: list[str]
    removed_names: list[str]

    @property
    def changed(self) -> bool:
        """Поменялось ли МНОЖЕСТВО (а не порядок).

        Перестановка пишется в БД, но не порождает ни activity, ни
        уведомлений — иначе drag-сортировка аватаров засорила бы ленту.
        """
        return bool(self.added or self.removed)


def _display_name(full_name: str | None, email: str | None) -> str:
    return full_name or email or "—"


def serialize_with_assignees(
    task: Task, assignees: list[AssigneeBrief]
) -> TaskResponse:
    """TaskResponse с исполнителями + легаси-зеркалами.

    Легаси-поля ВСЕГДА выводятся из списка, а не из ORM-атрибута — поэтому
    удаление колонки-зеркала tasks.assignee_id (0036) не тронуло сериализацию,
    а assignee_id/assignee больше не могут разъехаться (раньше у уволенного
    сотрудника assignee_id был непустым при assignee=null).
    """
    data = TaskResponse.model_validate(task)
    data.assignees = assignees
    first = assignees[0] if assignees else None
    data.assignee = first
    data.assignee_id = first.employee_id if first else None
    return data


# ─── Чтение ─────────────────────────────────────────────────────────────────


async def load_assignees(
    db: AsyncSession, task_ids: Sequence[UUID]
) -> dict[UUID, list[AssigneeBrief]]:
    """{task_id: [brief, ...]} одним запросом на чанк.

    Уволенные скрыты (`deleted_at IS NULL`) — инвариант «удалённый в auth не
    появляется в списках» из CLAUDE.md.
    """
    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {}
    out: dict[UUID, list[AssigneeBrief]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        rows = await db.execute(
            select(
                TaskAssignee.task_id,
                ShadowUser.employee_id,
                ShadowUser.email,
                ShadowUser.full_name,
            )
            .join(
                ShadowUser,
                (ShadowUser.employee_id == TaskAssignee.employee_id)
                & (ShadowUser.deleted_at.is_(None)),
            )
            .where(TaskAssignee.task_id.in_(chunk))
            .order_by(
                TaskAssignee.task_id, TaskAssignee.position, TaskAssignee.employee_id
            )
        )
        for row in rows.all():
            out.setdefault(row.task_id, []).append(
                AssigneeBrief(
                    employee_id=row.employee_id,
                    email=row.email,
                    full_name=row.full_name,
                )
            )
    return out


async def load_assignee_ids(
    db: AsyncSession, task_ids: Sequence[UUID]
) -> dict[UUID, list[UUID]]:
    """Сырые employee_id БЕЗ фильтра deleted_at — для получателей уведомлений.

    Паритет с прежним поведением одиночного исполнителя, которое на deleted_at
    тоже не смотрело.
    """
    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {}
    out: dict[UUID, list[UUID]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        rows = await db.execute(
            select(TaskAssignee.task_id, TaskAssignee.employee_id)
            .where(TaskAssignee.task_id.in_(chunk))
            .order_by(
                TaskAssignee.task_id, TaskAssignee.position, TaskAssignee.employee_id
            )
        )
        for task_id, employee_id in rows.all():
            out.setdefault(task_id, []).append(employee_id)
    return out


def assignee_exists(employee_id: UUID):  # noqa: ANN201 — SQLAlchemy Exists
    """EXISTS-предикат «employee_id среди исполнителей задачи».

    Единственный допустимый способ фильтровать списки по исполнителю: JOIN
    размножил бы строки задачи.
    """
    return (
        select(TaskAssignee.task_id)
        .where(
            TaskAssignee.task_id == Task.id,
            TaskAssignee.employee_id == employee_id,
        )
        .exists()
    )


def has_no_assignees():  # noqa: ANN201 — SQLAlchemy Exists
    """Предикат «у задачи нет ни одного исполнителя» (бакет workload)."""
    return ~select(TaskAssignee.task_id).where(TaskAssignee.task_id == Task.id).exists()


async def collect_recipients(
    db: AsyncSession, task_ids: Sequence[UUID]
) -> dict[UUID, set[UUID]]:
    """{task_id: watchers ∪ assignees} — получатели напоминаний джобов.

    Батчем: раньше джобы делали по запросу за watcher'ами на каждую задачу.
    Только чтение — джобы ходят с bypass_rls, а политики без WITH CHECK.
    """
    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {}
    out: dict[UUID, set[UUID]] = {tid: set() for tid in ids}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        watchers = await db.execute(
            select(TaskWatcher.task_id, TaskWatcher.employee_id).where(
                TaskWatcher.task_id.in_(chunk)
            )
        )
        for task_id, employee_id in watchers.all():
            out[task_id].add(employee_id)
        assignees = await db.execute(
            select(TaskAssignee.task_id, TaskAssignee.employee_id).where(
                TaskAssignee.task_id.in_(chunk)
            )
        )
        for task_id, employee_id in assignees.all():
            out[task_id].add(employee_id)
    return out


# ─── Валидация ──────────────────────────────────────────────────────────────


async def assert_assignees_in_tenant(
    db: AsyncSession, employee_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """{employee_id: отображаемое имя}; 404, если кого-то нет в Hub.

    Только сотрудники, хоть раз заходившие в Hub (= есть в shadow_users).
    Tenant режет RLS. Звать ДО любых записей и ДО _allocate_task_seq (тот
    держит row-lock проекта до конца транзакции).
    """
    ids = dedupe(employee_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(ShadowUser.employee_id, ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id.in_(ids), ShadowUser.deleted_at.is_(None)
        )
    )
    found = {
        row.employee_id: _display_name(row.full_name, row.email) for row in rows.all()
    }
    if len(found) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исполнитель не найден в Hub. Попросите его зайти на hub.signaris.ru.",
        )
    return found


# ─── Запись ─────────────────────────────────────────────────────────────────


async def _current_names(db: AsyncSession, task_id: UUID) -> dict[UUID, str]:
    rows = await db.execute(
        select(TaskAssignee.employee_id, ShadowUser.full_name, ShadowUser.email)
        .join(ShadowUser, ShadowUser.employee_id == TaskAssignee.employee_id, isouter=True)
        .where(TaskAssignee.task_id == task_id)
        .order_by(TaskAssignee.position, TaskAssignee.employee_id)
    )
    return {
        row.employee_id: _display_name(row.full_name, row.email) for row in rows.all()
    }


async def set_task_assignees(
    db: AsyncSession,
    *,
    task: Task,
    employee_ids: Sequence[UUID],
    actor_id: UUID,
    validated_names: dict[UUID, str] | None = None,
) -> AssigneeDiff:
    """Replace-семантика: набор становится ровно `employee_ids`.

    Звать строго ПОСЛЕ `db.flush()` для новых задач — FK task_assignees.task_id
    требует, чтобы строка задачи уже была в Postgres (та же ловушка, что с
    record_activity в tasks.py).
    """
    final = dedupe(employee_ids)
    if len(final) > MAX_ASSIGNEES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {MAX_ASSIGNEES} исполнителей на задачу",
        )
    names = validated_names
    if names is None:
        names = await assert_assignees_in_tenant(db, final)

    existing_names = await _current_names(db, task.id)
    existing = set(existing_names)
    wanted = set(final)
    added = [e for e in final if e not in existing]
    removed = [e for e in existing_names if e not in wanted]

    if removed:
        await db.execute(
            delete(TaskAssignee).where(
                TaskAssignee.task_id == task.id,
                TaskAssignee.employee_id.in_(removed),
            )
        )
    if final:
        stmt = pg_insert(TaskAssignee).values(
            [
                {
                    "task_id": task.id,
                    "employee_id": employee_id,
                    "tenant_id": task.tenant_id,
                    "position": idx,
                    "assigned_by": actor_id,
                }
                for idx, employee_id in enumerate(final)
            ]
        )
        # Upsert, а не INSERT: перестановка существующих строк меняет position.
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["task_id", "employee_id"],
                set_={"position": stmt.excluded.position},
            )
        )


    return AssigneeDiff(
        final=final,
        added=added,
        removed=removed,
        added_names=[names.get(e, "—") for e in added],
        removed_names=[existing_names.get(e, "—") for e in removed],
    )


async def add_assignee(
    db: AsyncSession, *, task: Task, employee_id: UUID, actor_id: UUID
) -> AssigneeDiff:
    """Добавить одного, идемпотентно — без чтения набора клиентом.

    Инкрементальный путь защищает от потерянных обновлений: replace-семантика
    PATCH'а затирала бы исполнителя, добавленного параллельно другим человеком.
    """
    names = await assert_assignees_in_tenant(db, [employee_id])
    existing_names = await _current_names(db, task.id)
    if employee_id in existing_names:
        return AssigneeDiff(
            final=list(existing_names),
            added=[],
            removed=[],
            added_names=[],
            removed_names=[],
        )
    if len(existing_names) + 1 > MAX_ASSIGNEES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {MAX_ASSIGNEES} исполнителей на задачу",
        )
    next_position = (
        await db.execute(
            select(func.coalesce(func.max(TaskAssignee.position) + 1, 0)).where(
                TaskAssignee.task_id == task.id
            )
        )
    ).scalar_one()
    await db.execute(
        pg_insert(TaskAssignee)
        .values(
            task_id=task.id,
            employee_id=employee_id,
            tenant_id=task.tenant_id,
            position=next_position,
            assigned_by=actor_id,
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )
    final = [*existing_names, employee_id]
    return AssigneeDiff(
        final=final,
        added=[employee_id],
        removed=[],
        added_names=[names.get(employee_id, "—")],
        removed_names=[],
    )


async def remove_assignee(
    db: AsyncSession, *, task: Task, employee_id: UUID, actor_id: UUID
) -> AssigneeDiff:
    """Снять одного, идемпотентно. actor_id в подписи — для симметрии вызовов."""
    _ = actor_id
    existing_names = await _current_names(db, task.id)
    if employee_id not in existing_names:
        return AssigneeDiff(
            final=list(existing_names),
            added=[],
            removed=[],
            added_names=[],
            removed_names=[],
        )
    await db.execute(
        delete(TaskAssignee).where(
            TaskAssignee.task_id == task.id,
            TaskAssignee.employee_id == employee_id,
        )
    )
    final = [e for e in existing_names if e != employee_id]
    return AssigneeDiff(
        final=final,
        added=[],
        removed=[employee_id],
        added_names=[],
        removed_names=[existing_names[employee_id]],
    )


# ─── Побочные эффекты ───────────────────────────────────────────────────────


async def apply_assignee_side_effects(
    db: AsyncSession,
    *,
    task: Task,
    diff: AssigneeDiff,
    actor_id: UUID,
    actor_name: str,
    notify: bool = True,
    record: bool = True,
) -> None:
    """Watcher + членство + activity + уведомления по диффу.

    `removed` НЕ трогаем: снятый исполнитель остаётся watcher'ом и участником
    проекта — сегодняшняя семантика (см. docstring ensure_project_member).
    `notify=False`/`record=False` — для create_task: создание задачи с
    исполнителем уведомлений не шлёт и отдельного события «assigned» не пишет
    (лента начинается с «created»).
    """
    for employee_id in diff.added:
        await ensure_watcher(
            db,
            task_id=task.id,
            tenant_id=task.tenant_id,
            employee_id=employee_id,
            reason="assignee",
        )
        # Исполнитель без членства не может открыть проект из «Все задачи»
        # (404) — авто-viewer чинит deep-link; существующая роль не трогается.
        await ensure_project_member(
            db,
            project_id=task.project_id,
            tenant_id=task.tenant_id,
            employee_id=employee_id,
            added_by=actor_id,
        )

    if record:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=actor_id,
            kind="assigned",
            payload={
                # Легаси-зеркала: старые PWA-бандлы рендерят ленту по old/new.
                "old": str(diff.removed[0]) if diff.removed and not diff.added else None,
                "new": str(diff.final[0]) if diff.final else None,
                "added": [str(e) for e in diff.added],
                "removed": [str(e) for e in diff.removed],
                "assignee_ids": [str(e) for e in diff.final],
                # Снапшот имён — переживает удаление сотрудника и не требует
                # доп. запроса при рендере (паттерн сертификатов/аттестаций).
                "added_names": diff.added_names,
                "removed_names": diff.removed_names,
            },
        )

    if notify:
        for employee_id in diff.added:
            if employee_id == actor_id:
                continue
            await notify_assigned(
                db, task=task, assignee_id=employee_id, actor_name=actor_name
            )
