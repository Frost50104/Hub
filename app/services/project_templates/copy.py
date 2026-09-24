"""Копирование проекта в шаблон и шаблона в проект — один код, два шага (0060).

`plan_copy` только читает (он же кормит предпросмотр в диалогах),
`apply_copy` пишет и НЕ коммитит — как `task_move.plan_move/apply_move`.

Запись пачками, а не по задаче: цикл по образцу `_clone_task` — это ~10
обращений к базе на задачу, и проект на 1 745 задач (крупнейший на проде)
держал бы единственный воркер секундами. Здесь число запросов не зависит от
размера: ~12 SELECT на чтение и ~15 INSERT на запись (`executemany`).

Обе стороны видны вызывающему: область шаблона (`app/db.py`) он открыл
заранее — `'<id шаблона>'` при создании проекта и при сохранении нового
шаблона (живой источник виден всегда).

Файлы вложений (`clone_blob`) пишутся ДО commit; вызывающий передаёт
`created_keys` и на любом исключении снимает их `purge_blobs` — строки БД
не могут указывать в пустоту, а байты не должны осиротеть.
"""

from __future__ import annotations

import asyncio
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import exists, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.attachment import TaskAttachment
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.dependency import TaskDependency
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.stage import ProjectStage
from app.models.task import (
    Task,
    TaskAssignee,
    TaskLabel,
    TaskLabelAssignment,
    TaskRecurrence,
    TaskWatcher,
)
from app.services.activity_writer import record_activities
from app.services.attachments import absolute_path, clone_blob, storage_key_for
from app.services.project_badge import storage_key_for_badge
from app.services.project_templates import rows
from app.services.taskdates import due_day
from app.services.tasks import allocate_task_seq_block

# Потолок вместе с подзадачами — как `_MAX_ROWS` импорта CSV. Крупнейший
# проект прода — 1 745 задач (LM), все текущие проекты под потолком.
TEMPLATE_MAX_TASKS = 2000


@dataclass
class CopyPlan:
    src: Project
    selection: rows.Selection
    stages: list[ProjectStage]
    labels: list[TaskLabel]
    fields: list[CustomFieldDefinition]
    assignees: list[rows.Person]
    watchers: list[rows.Person]
    label_links: list[tuple[UUID, UUID]]
    field_values: list[tuple[UUID, UUID, Any]]
    dependencies: list[tuple[UUID, UUID]]
    recurrences: list[TaskRecurrence]
    attachments: list[TaskAttachment]
    members: list[tuple[UUID, str, bool]]
    dead_people: set[UUID]
    names: dict[UUID, str]

    @property
    def task_count(self) -> int:
        return len(self.selection.ordered)

    @property
    def too_big(self) -> bool:
        return self.task_count > TEMPLATE_MAX_TASKS

    @property
    def attachment_bytes(self) -> int:
        return sum(int(a.size_bytes or 0) for a in self.attachments)


@dataclass
class CopyReport:
    tasks: int = 0
    subtasks: int = 0
    dropped: rows.Dropped = field(default_factory=rows.Dropped)
    dropped_people: list[dict[str, Any]] = field(default_factory=list)
    attachments_copied: int = 0
    attachments_linked: int = 0
    attachments_missing: int = 0
    summary: dict[UUID, int] = field(default_factory=dict)


async def plan_copy(
    db: AsyncSession,
    src: Project,
    *,
    include_members: bool = True,
    include_attachments: bool = True,
) -> CopyPlan:
    child = aliased(Task)
    task_rows = (
        await db.execute(
            select(
                Task.id,
                Task.parent_task_id,
                Task.stage_id,
                Task.title,
                Task.description,
                Task.priority,
                Task.start_at,
                Task.due_at,
                Task.position,
                Task.seq,
                Task.done,
                Task.archived_at.is_not(None),
                exists().where(child.recurrence_parent_id == Task.id),
                Task.start_has_time,
                Task.due_has_time,
            ).where(Task.project_id == src.id)
        )
    ).all()
    selection = rows.select_tasks(
        [
            rows.SrcTask(
                id=r[0],
                parent_task_id=r[1],
                stage_id=r[2],
                title=r[3],
                description=r[4],
                priority=r[5],
                start_at=r[6],
                due_at=r[7],
                position=r[8],
                seq=r[9],
                done=r[10],
                archived=bool(r[11]),
                has_recurrence_child=bool(r[12]),
                start_has_time=bool(r[13]),
                due_has_time=bool(r[14]),
            )
            for r in task_rows
        ]
    )
    kept = selection.ids
    in_project = Task.project_id == src.id

    stages = list(
        (
            await db.execute(
                select(ProjectStage)
                .where(ProjectStage.project_id == src.id)
                .order_by(ProjectStage.position)
            )
        ).scalars()
    )
    labels = list(
        (await db.execute(select(TaskLabel).where(TaskLabel.project_id == src.id))).scalars()
    )
    fields = list(
        (
            await db.execute(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.project_id == src.id)
                .order_by(CustomFieldDefinition.position)
            )
        ).scalars()
    )

    assignees = [
        rows.Person(task_id=t, employee_id=e, alive=d is None, position=pos)
        for t, e, pos, d in (
            await db.execute(
                select(
                    TaskAssignee.task_id,
                    TaskAssignee.employee_id,
                    TaskAssignee.position,
                    ShadowUser.deleted_at,
                )
                .join(Task, Task.id == TaskAssignee.task_id)
                .join(ShadowUser, ShadowUser.employee_id == TaskAssignee.employee_id)
                .where(in_project)
                .order_by(TaskAssignee.task_id, TaskAssignee.position)
            )
        ).all()
        if t in kept
    ]
    watchers = [
        rows.Person(task_id=t, employee_id=e, alive=d is None, reason=reason)
        for t, e, reason, d in (
            await db.execute(
                select(
                    TaskWatcher.task_id,
                    TaskWatcher.employee_id,
                    TaskWatcher.added_reason,
                    ShadowUser.deleted_at,
                )
                .join(Task, Task.id == TaskWatcher.task_id)
                .join(ShadowUser, ShadowUser.employee_id == TaskWatcher.employee_id)
                .where(in_project)
            )
        ).all()
        if t in kept
    ]
    label_links = [
        (t, lbl)
        for t, lbl in (
            await db.execute(
                select(TaskLabelAssignment.task_id, TaskLabelAssignment.label_id)
                .join(Task, Task.id == TaskLabelAssignment.task_id)
                .where(in_project)
            )
        ).all()
        if t in kept
    ]
    field_values = [
        (t, f, v)
        for t, f, v in (
            await db.execute(
                select(
                    TaskCustomFieldValue.task_id,
                    TaskCustomFieldValue.field_id,
                    TaskCustomFieldValue.value,
                )
                .join(Task, Task.id == TaskCustomFieldValue.task_id)
                .where(in_project)
            )
        ).all()
        if t in kept
    ]
    # Межпроектных зависимостей нет (dependencies.py запрещает), но строка с
    # концом вне набора возможна — архивный или отброшенный конец.
    dependencies = [
        (p, s)
        for p, s in (
            await db.execute(
                select(TaskDependency.predecessor_id, TaskDependency.successor_id)
                .join(Task, Task.id == TaskDependency.successor_id)
                .where(in_project)
            )
        ).all()
        if p in kept and s in kept
    ]
    recurrences = [
        r
        for r in (
            await db.execute(
                select(TaskRecurrence)
                .join(Task, Task.id == TaskRecurrence.task_id)
                .where(in_project)
            )
        ).scalars()
        if r.task_id in kept
    ]
    attachments: list[TaskAttachment] = []
    if include_attachments:
        attachments = [
            a
            for a in (
                await db.execute(
                    select(TaskAttachment)
                    .join(Task, Task.id == TaskAttachment.task_id)
                    .where(in_project)
                    .order_by(TaskAttachment.created_at)
                )
            ).scalars()
            if a.task_id in kept
        ]
    members: list[tuple[UUID, str, bool]] = []
    if include_members:
        members = [
            (e, role, d is None)
            for e, role, d in (
                await db.execute(
                    select(ProjectMember.employee_id, ProjectMember.role, ShadowUser.deleted_at)
                    .join(ShadowUser, ShadowUser.employee_id == ProjectMember.employee_id)
                    .where(ProjectMember.project_id == src.id)
                )
            ).all()
        ]

    # Поле «человек»: уволенный в значении выпадает, как исполнитель.
    person_fields = {f.id for f in fields if f.type == "person"}
    person_ids: set[UUID] = set()
    for _t, f, v in field_values:
        if f in person_fields and isinstance(v, str):
            try:
                person_ids.add(UUID(v))
            except ValueError:
                continue
    dead_people = {p.employee_id for p in [*assignees, *watchers] if not p.alive}
    dead_people |= {e for e, _r, alive in members if not alive}
    if person_ids:
        dead_people |= set(
            (
                await db.execute(
                    select(ShadowUser.employee_id).where(
                        ShadowUser.employee_id.in_(person_ids),
                        ShadowUser.deleted_at.is_not(None),
                    )
                )
            ).scalars()
        )
    names: dict[UUID, str] = {}
    if dead_people:
        names = {
            e: (n or em or "")
            for e, n, em in (
                await db.execute(
                    select(ShadowUser.employee_id, ShadowUser.full_name, ShadowUser.email).where(
                        ShadowUser.employee_id.in_(dead_people)
                    )
                )
            ).all()
        }
    return CopyPlan(
        src=src,
        selection=selection,
        stages=stages,
        labels=labels,
        fields=fields,
        assignees=assignees,
        watchers=watchers,
        label_links=label_links,
        field_values=field_values,
        dependencies=dependencies,
        recurrences=recurrences,
        attachments=attachments,
        members=members,
        dead_people=dead_people,
        names=names,
    )


def dropped_people_report(plan: CopyPlan) -> list[dict[str, Any]]:
    """Уволенные, выпавшие из задач и состава — по имени, для предпросмотра."""
    per_task = rows.dropped_people(plan.assignees, plan.watchers, plan.selection.ids)
    out: Counter[UUID] = Counter(per_task)
    for e, _role, alive in plan.members:
        if not alive:
            out.setdefault(e, 0)
    return [
        {"employee_id": str(e), "name": plan.names.get(e, ""), "tasks": n}
        for e, n in sorted(out.items(), key=lambda kv: (-kv[1], plan.names.get(kv[0], "")))
    ]


async def _copy_badge(src: Project, dst: Project, created_keys: list[str]) -> None:
    dst.badge_emoji = src.badge_emoji
    if not src.badge_storage_key or not src.badge_mime:
        return
    key = storage_key_for_badge(dst.tenant_id, dst.id, src.badge_mime)

    def _copy() -> bool:
        source = absolute_path(src.badge_storage_key or "")
        if not source.is_file():
            return False
        target = absolute_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Копия байтов, а не ссылка: бейдж меньше лимита в килобайтах, а ключ
        # у него и так новый на каждую заливку.
        shutil.copyfile(source, target)
        return True

    if await asyncio.to_thread(_copy):
        created_keys.append(key)
        dst.badge_storage_key = key
        dst.badge_mime = src.badge_mime


async def apply_copy(
    db: AsyncSession,
    plan: CopyPlan,
    dst: Project,
    *,
    actor_id: UUID,
    shift: int,
    created_keys: list[str],
    template_ref: tuple[UUID, str] | None = None,
) -> CopyReport:
    """Записать копию в `dst` (уже вставленный, пустой). Без commit.

    `dst.is_template` решает сторону: в шаблон — задачи шаблона, состав
    только явный (без автоматических viewer'ов), без сводки; в живой проект —
    `template_copy`, viewer всем исполнителям и наблюдателям, сводка.
    """
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    await db.execute(text("SET LOCAL statement_timeout = '60s'"))
    to_template = dst.is_template
    tenant_id = dst.tenant_id
    sel = plan.selection
    report = CopyReport(dropped=sel.dropped, dropped_people=dropped_people_report(plan))

    # Колонки, метки, поля — по карте id (имена колонок не уникальны).
    stage_map = {s.id: uuid4() for s in plan.stages}
    if plan.stages:
        await db.execute(
            insert(ProjectStage),
            [
                {
                    "id": stage_map[s.id],
                    "tenant_id": tenant_id,
                    "project_id": dst.id,
                    "name": s.name,
                    "position": s.position,
                }
                for s in plan.stages
            ],
        )
    label_map = {lbl.id: uuid4() for lbl in plan.labels}
    if plan.labels:
        await db.execute(
            insert(TaskLabel),
            [
                {
                    "id": label_map[lbl.id],
                    "tenant_id": tenant_id,
                    "project_id": dst.id,
                    "name": lbl.name,
                    "color": lbl.color,
                }
                for lbl in plan.labels
            ],
        )
    field_map = {f.id: uuid4() for f in plan.fields}
    field_type = {f.id: f.type for f in plan.fields}
    if plan.fields:
        # `options` как есть: id опций живут внутри JSONB, и значения
        # select/multi_select переносятся без пересборки.
        await db.execute(
            insert(CustomFieldDefinition),
            [
                {
                    "id": field_map[f.id],
                    "tenant_id": tenant_id,
                    "project_id": dst.id,
                    "name": f.name,
                    "type": f.type,
                    "options": f.options or [],
                    "position": f.position,
                }
                for f in plan.fields
            ],
        )

    task_map = {t.id: uuid4() for t in sel.ordered}
    if task_map:
        first = await allocate_task_seq_block(db, dst.id, len(task_map))
        seqs = rows.seq_map(sel, first)

        def _task_row(t: rows.SrcTask) -> dict[str, Any]:
            return {
                "id": task_map[t.id],
                "tenant_id": tenant_id,
                "project_id": dst.id,
                "parent_task_id": task_map[t.parent_task_id] if t.parent_task_id else None,
                "stage_id": stage_map.get(t.stage_id) if t.stage_id else None,
                "title": t.title,
                "description": t.description,
                "priority": t.priority,
                "created_by": actor_id,
                "start_at": rows.shifted_start(t.start_at, shift),
                "due_at": rows.shifted_due(t.due_at, shift, t.due_has_time),
                "start_has_time": t.start_has_time and t.start_at is not None,
                "due_has_time": t.due_has_time and t.due_at is not None,
                "position": t.position,
                "seq": seqs[t.id],
                "done": False,
                "completed_at": None,
                "is_template": to_template,
                "template_copy": not to_template,
            }

        # Родители — отдельным INSERT до подзадач: триггер чётности читает
        # строку родителя.
        if sel.parents:
            await db.execute(insert(Task), [_task_row(t) for t in sel.parents])
        if sel.children:
            await db.execute(insert(Task), [_task_row(t) for t in sel.children])
        report.tasks = len(sel.parents)
        report.subtasks = len(sel.children)

    kept = sel.ids
    live = rows.live_assignees(plan.assignees, kept)
    if live:
        await db.execute(
            insert(TaskAssignee),
            [
                {
                    "task_id": task_map[a.task_id],
                    "employee_id": a.employee_id,
                    "tenant_id": tenant_id,
                    "position": a.position,
                    "assigned_by": actor_id,
                }
                for a in live
            ],
        )
    watcher_rows = rows.watchers_to_copy(plan.watchers, plan.assignees, kept)
    if watcher_rows:
        await db.execute(
            pg_insert(TaskWatcher).on_conflict_do_nothing(
                index_elements=["task_id", "employee_id"]
            ),
            [
                {
                    "task_id": task_map[t],
                    "employee_id": e,
                    "tenant_id": tenant_id,
                    "added_reason": reason,
                }
                for t, e, reason in watcher_rows
            ],
        )
    link_rows = [
        {"task_id": task_map[t], "label_id": label_map[lbl], "tenant_id": tenant_id}
        for t, lbl in plan.label_links
        if lbl in label_map
    ]
    if link_rows:
        await db.execute(insert(TaskLabelAssignment), link_rows)
    value_rows: list[dict[str, Any]] = []
    for t, f, v in plan.field_values:
        if f not in field_map:
            continue
        ftype = field_type[f]
        if ftype == "person" and isinstance(v, str):
            try:
                if UUID(v) in plan.dead_people:
                    continue
            except ValueError:
                continue
        value = rows.shifted_date_value(v, shift) if ftype == "date" else v
        value_rows.append(
            {
                "task_id": task_map[t],
                "field_id": field_map[f],
                "tenant_id": tenant_id,
                "value": value,
            }
        )
    if value_rows:
        await db.execute(insert(TaskCustomFieldValue), value_rows)
    if plan.dependencies:
        await db.execute(
            insert(TaskDependency),
            [
                {
                    "predecessor_id": task_map[p],
                    "successor_id": task_map[s],
                    "tenant_id": tenant_id,
                }
                for p, s in plan.dependencies
            ],
        )
    # Повтор: якорь серии — новый срок, счётчик шагов с нуля. Без срока
    # правила не бывает (ручка повтора его требует), такую строку пропускаем.
    rec_rows: list[dict[str, Any]] = []
    src_by_id = {t.id: t for t in sel.ordered}
    for r in plan.recurrences:
        src_task = src_by_id[r.task_id]
        new_due = rows.shifted_due(src_task.due_at, shift, src_task.due_has_time)
        if new_due is None:
            continue
        rec_rows.append(
            {
                "task_id": task_map[r.task_id],
                "tenant_id": tenant_id,
                "freq": r.freq,
                "step": r.step,
                "anchor": due_day(new_due),
                "occurrence": 0,
                "created_by": actor_id,
            }
        )
    if rec_rows:
        await db.execute(insert(TaskRecurrence), rec_rows)

    # Вложения: новый путь на каждую копию (жёсткая ссылка или копия).
    # `uploaded_by` — тот, кто копирует: загрузивший удаляет вложение без
    # проверки доступа (`api/attachments.py::delete_attachment`), и исходный
    # автор файла мог бы удалять его в чужих проектах из шаблона.
    att_rows: list[dict[str, Any]] = []
    for a in plan.attachments:
        new_task = task_map[a.task_id]
        key, _ = storage_key_for(tenant_id, new_task, a.filename)
        outcome = await asyncio.to_thread(clone_blob, a.storage_key, key)
        if outcome == "missing":
            report.attachments_missing += 1
            continue
        created_keys.append(key)
        if outcome == "linked":
            report.attachments_linked += 1
        report.attachments_copied += 1
        att_rows.append(
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "task_id": new_task,
                "uploaded_by": actor_id,
                "filename": a.filename,
                "mime": a.mime,
                "size_bytes": a.size_bytes,
                "storage_key": key,
            }
        )
    if att_rows:
        await db.execute(insert(TaskAttachment), att_rows)

    # Состав. Сначала роль в роль (создающий уже owner — его строка
    # побеждает по ON CONFLICT), потом — только в живом проекте — viewer всем
    # исполнителям и наблюдателям: иначе пуш вёл бы в 404. В шаблоне состав
    # только явный (решение №12).
    member_rows = [
        {"id": uuid4(), "tenant_id": tenant_id, "project_id": dst.id, "employee_id": e,
         "role": role, "added_by": actor_id}
        for e, role in rows.members_to_copy(plan.members, exclude={actor_id})
    ]
    if not to_template:
        people = {a.employee_id for a in live} | {e for _t, e, _r in watcher_rows}
        people.discard(actor_id)
        member_rows += [
            {"id": uuid4(), "tenant_id": tenant_id, "project_id": dst.id, "employee_id": e,
             "role": "viewer", "added_by": actor_id}
            for e in sorted(people)
        ]
    if member_rows:
        await db.execute(
            pg_insert(ProjectMember).on_conflict_do_nothing(
                index_elements=["project_id", "employee_id"]
            ),
            member_rows,
        )

    # Лента: одна строка `created` на задачу. Вид прежний — старые бандлы
    # незнакомый вид показали бы сырым; новый допишет «по шаблону «X»».
    stage_names = {s.id: s.name for s in plan.stages}
    activity: list[dict[str, Any]] = []
    for t in sel.ordered:
        payload: dict[str, Any] = {
            "title": t.title,
            "stage_id": str(stage_map[t.stage_id]) if t.stage_id in stage_map else None,
            "stage_name": stage_names.get(t.stage_id) if t.stage_id else None,
        }
        if template_ref is not None:
            payload["template_id"] = str(template_ref[0])
            payload["template_name"] = template_ref[1]
        activity.append(
            {
                "tenant_id": tenant_id,
                "task_id": task_map[t.id],
                "actor_id": actor_id,
                "kind": "created",
                "payload": payload,
            }
        )
    await record_activities(db, activity)

    await _copy_badge(plan.src, dst, created_keys)
    if not to_template:
        report.summary = rows.summary_counts(plan.assignees, kept, exclude=actor_id)
    return report


def preview_payload(plan: CopyPlan, *, shift: int, today: date, actor_id: UUID) -> dict[str, Any]:
    """Что покажет диалог до нажатия — считает тот же код, что и копирует."""
    sel = plan.selection
    first, last = rows.date_range(sel, shift)
    summary = rows.summary_counts(plan.assignees, sel.ids, exclude=actor_id)
    return {
        "tasks": len(sel.parents),
        "subtasks": len(sel.children),
        "too_big": plan.too_big,
        "max_tasks": TEMPLATE_MAX_TASKS,
        "dropped": {
            "archived": sel.dropped.archived,
            "orphan_subtasks": sel.dropped.orphan_subtasks,
            "recurrence_steps": sel.dropped.recurrence_steps,
        },
        "dropped_people": dropped_people_report(plan),
        "attachments": len(plan.attachments),
        "attachment_bytes": plan.attachment_bytes,
        "members": sum(1 for _e, _r, alive in plan.members if alive),
        "notify_people": len(summary),
        "first_due": first,
        "last_due": last,
        "overdue_after_shift": rows.overdue_after_shift(sel, shift, today),
        "due_soon_reminders": rows.due_within(sel, shift, today),
        "suggested_anchor_on": rows.suggested_anchor(sel, today),
    }
