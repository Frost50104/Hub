"""Перенос задачи в другой проект: сначала план, потом его исполнение.

До 28.08 `tasks.project_id` был доменно иммутабелен, и переносила задачи только
одноразовая джоба `app/jobs/split_project_by_labels.py`. Цена, из-за которой
иммутабельность держалась, никуда не делась: номер «KEY-42» уникален внутри
проекта (`uq_tasks_project_seq`), поэтому переезд ОБЯЗАН перенумеровать задачу,
и ссылки на старый номер в переписке перестают на неё указывать. Значит перенос
не может быть тихим селектом — он показывает человеку последствия и только
потом пишет.

Отсюда деление на две функции. **`plan_move` считает, `apply_move` исполняет
посчитанное.** Предпросмотр в диалоге и сама запись идут по ОДНОМУ коду; вторая
реализация правил «что переедет» разошлась бы с первой на первой же правке.

Почему план, а не `dry_run` с откатом (как у импорта CSV): `allocate_task_seq`
инкрементит `projects.next_task_seq` до отката, и диалог, в котором человек
перебирает пять целей, оставил бы дыру в нумерации каждой из них. `plan_move`
не пишет вообще ничего — номер выдаёт только `apply_move`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.dependency import TaskDependency
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.share import PublicShareToken
from app.models.stage import ProjectStage
from app.models.task import (
    Task,
    TaskAssignee,
    TaskLabel,
    TaskLabelAssignment,
    TaskWatcher,
)
from app.services.activity_writer import record_activity
from app.services.custom_field_validator import CustomFieldValueError, validate
from app.services.project_access import ensure_project_member
from app.services.projects import assert_project_accepts_tasks
from app.services.stages import get_stage_in_project, next_position
from app.services.tasks import allocate_task_seq

# Значения `select`/`multi_select` хранятся id'шниками опций, а id у одноимённых
# полей разных проектов свои — эти два типа переносятся не как есть.
_OPTION_TYPES = ("select", "multi_select")


@dataclass
class MovePlan:
    """Что именно случится с задачей и её семьёй при переезде.

    Один объект на предпросмотр и на запись: `apply_move` не пересчитывает
    ничего, а раскладывает уже посчитанное.
    """

    source: Project
    target: Project
    # Семья по возрастанию СТАРОГО seq: внутри нового проекта порядок создания
    # обязан сохраниться, иначе «первая» задача становится случайной.
    tasks: list[Task]
    # task_id → колонка цели (None — «без статуса», законное состояние 0046).
    stages: dict[UUID, UUID | None]
    # (task_id, label_id цели) — метки, для которых в цели нашлась одноимённая.
    labels_keep: list[tuple[UUID, UUID]]
    labels_total: int
    # (task_id, field_id цели, значение под целевое поле).
    values_keep: list[tuple[UUID, UUID, Any]]
    values_total: int
    # (task_id, employee_id) — наблюдатели, которые в цели остались бы без
    # доступа: подписка на задачу, которую не открыть, ведёт по пушу в 403.
    watchers_drop: list[tuple[UUID, UUID]]
    dependencies_drop: int
    # Активные публичные ссылки scope=task на переезжающих задачах.
    shares_revoke: int
    # У цели есть активная ссылка scope=project — задача станет видна анонимам.
    target_public: bool
    # Заполняет apply_move: task_id → «KEY-42» в новом проекте.
    new_keys: dict[UUID, str] = field(default_factory=dict)

    @property
    def subtasks(self) -> int:
        return len(self.tasks) - 1


def _active_token() -> Any:
    """«Ссылка ещё работает» — как в `public_token.load_active_token`."""
    now = datetime.now(UTC)
    return and_(
        PublicShareToken.revoked_at.is_(None),
        or_(
            PublicShareToken.expires_at.is_(None),
            PublicShareToken.expires_at > now,
        ),
    )


async def assert_movable(
    *, task: Task, source: Project, target: Project, principal: Principal
) -> None:
    """Запреты, которые не выводятся из ролей.

    Личный проект отдельным гейтом, а не общим `require_project_role`: тот
    пропускает hub-admin мимо членства, а `personal_task_scope` для админа
    возвращает None — то есть без этой проверки админ вытаскивал бы чужие
    личные заметки в общий проект и заталкивал задачи в чужое личное.
    """
    if task.parent_task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Подзадача переезжает только вместе с родительской задачей",
        )
    if target.id == task.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Задача уже в этом проекте",
        )
    # Тот же гейт и тот же текст, что у создания задачи: «в архив не пишем» —
    # одно правило, и разные формулировки читались бы как разные.
    assert_project_accepts_tasks(target)
    for project in (source, target):
        owner = project.personal_owner_id
        if owner is not None and owner != principal.employee_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Чужое личное пространство в переносе не участвует",
            )


async def _family(db: AsyncSession, task: Task) -> list[Task]:
    """Задача и её подзадачи, по возрастанию старого `seq`.

    Семью не рвём: `tasks.parent_task_id` — обычный FK на `tasks.id` без
    проектного ограничения, БД разрыв стерпит, а карточка нет — `SubtaskList`
    ищет детей в списке НОВОГО проекта и покажет ноль.
    """
    children = (
        (
            await db.execute(
                select(Task).where(Task.parent_task_id == task.id).order_by(Task.seq)
            )
        )
        .scalars()
        .all()
    )
    return sorted([task, *children], key=lambda t: t.seq)


async def _stage_map(
    db: AsyncSession,
    *,
    tasks: list[Task],
    source_id: UUID,
    target_id: UUID,
    stage_id: UUID | None,
) -> dict[UUID, UUID | None]:
    """Колонка каждой переезжающей задачи в целевом проекте.

    У корневой — ровно та, что пришла в запросе (`None` = «без статуса»);
    у подзадач — одноимённая, спрашивать про каждую было бы издевательством.
    Правило «корень берёт переданное» без исключений держит предпросмотр и
    перенос в согласии: у GET нет `model_fields_set`, и «не передали» с
    «передали null» там не различить — любая попытка развести эти случаи
    развела бы и два ответа. Дружелюбный дефолт живёт в диалоге: он
    подставляет одноимённую колонку сам. Оставить
    `stage_id` как есть нельзя: FK на `project_stages.id` проектом не ограничен
    и намеренно без `SET NULL`, поэтому строка с чужой колонкой прекрасно
    сохранится, а на доске цели такая задача не появится никогда.

    Имя не совпало — `None`. Через `.get()`, а не индекс, как в
    `split_project_by_labels`: там колонки цели копировались из источника и
    совпадение было гарантировано, здесь проект чужой.
    """
    src_names = dict(
        (
            await db.execute(
                select(ProjectStage.id, ProjectStage.name).where(
                    ProjectStage.project_id == source_id
                )
            )
        ).all()
    )
    dst_ids = dict(
        (
            await db.execute(
                select(ProjectStage.name, ProjectStage.id).where(
                    ProjectStage.project_id == target_id
                )
            )
        ).all()
    )

    def by_name(current: UUID | None) -> UUID | None:
        if current is None:
            return None
        return dst_ids.get(src_names.get(current, ""))

    out: dict[UUID, UUID | None] = {}
    for task in tasks:
        if task.parent_task_id is None:
            out[task.id] = stage_id
        else:
            out[task.id] = by_name(task.stage_id)
    return out


async def _plan_labels(
    db: AsyncSession, *, task_ids: list[UUID], target_id: UUID
) -> tuple[list[tuple[UUID, UUID]], int]:
    """Метки переезжают по точному совпадению имени (решение владельца).

    Метка живёт внутри проекта (`task_labels.project_id`), поэтому назначение
    на чужую метку — чужой чип в карточке. Новых меток в целевом проекте не
    заводим: перенос задачи не должен молча править справочник чужого проекта.
    """
    rows = (
        await db.execute(
            select(TaskLabelAssignment.task_id, TaskLabel.name)
            .join(TaskLabel, TaskLabel.id == TaskLabelAssignment.label_id)
            .where(TaskLabelAssignment.task_id.in_(task_ids))
        )
    ).all()
    dst = dict(
        (
            await db.execute(
                select(TaskLabel.name, TaskLabel.id).where(
                    TaskLabel.project_id == target_id
                )
            )
        ).all()
    )
    keep = [
        (task_id, dst[name]) for task_id, name in rows if name in dst
    ]
    return keep, len(rows)


def _remap_option_value(
    *, value: Any, source: CustomFieldDefinition, target: CustomFieldDefinition
) -> Any:
    """Значение select/multi_select — id опции, а id у цели свои.

    Пересобираем по ЛЕЙБЛУ: он и есть то, что человек видел в карточке.
    Неразрешимые опции выбрасываем; не осталось ничего — значения нет.
    """
    label_by_id = {
        str(o.get("id")): o.get("label") for o in (source.options or []) if "id" in o
    }
    id_by_label = {
        o.get("label"): str(o.get("id")) for o in (target.options or []) if "id" in o
    }

    def one(raw: Any) -> str | None:
        return id_by_label.get(label_by_id.get(str(raw)))

    if target.type == "select":
        return one(value)
    mapped = [m for m in (one(v) for v in (value or [])) if m is not None]
    return mapped or None


async def _plan_values(
    db: AsyncSession, *, task_ids: list[UUID], target_id: UUID
) -> tuple[list[tuple[UUID, UUID, Any]], int]:
    """Значения кастом-полей — по совпадению ИМЕНИ И ТИПА.

    Одного имени мало: `value` — JSONB, форма которого задана типом
    (`custom_field_validator`), и совпадение по имени пустило бы число в
    текстовое поле. Ошибка всплыла бы не здесь, а у человека на первой правке.

    Финальный фильтр — сам валидатор целевого поля: не прошло, значит не
    переехало. Так правило остаётся одно на запись и на перенос.
    """
    rows = (
        await db.execute(
            select(
                TaskCustomFieldValue.task_id,
                TaskCustomFieldValue.value,
                CustomFieldDefinition,
            )
            .join(
                CustomFieldDefinition,
                CustomFieldDefinition.id == TaskCustomFieldValue.field_id,
            )
            .where(TaskCustomFieldValue.task_id.in_(task_ids))
        )
    ).all()
    dst_defs = (
        (
            await db.execute(
                select(CustomFieldDefinition).where(
                    CustomFieldDefinition.project_id == target_id
                )
            )
        )
        .scalars()
        .all()
    )
    dst_by_shape = {(d.name, d.type): d for d in dst_defs}

    keep: list[tuple[UUID, UUID, Any]] = []
    for task_id, value, src_def in rows:
        dst_def = dst_by_shape.get((src_def.name, src_def.type))
        if dst_def is None:
            continue
        moved = (
            _remap_option_value(value=value, source=src_def, target=dst_def)
            if dst_def.type in _OPTION_TYPES
            else value
        )
        if moved is None:
            continue
        try:
            keep.append((task_id, dst_def.id, validate(dst_def, moved)))
        except CustomFieldValueError:
            continue
    return keep, len(rows)


async def _plan_watchers(
    db: AsyncSession, *, task_ids: list[UUID], target_id: UUID, actor_id: UUID
) -> list[tuple[UUID, UUID]]:
    """Наблюдатели, которые в цели остались бы без доступа.

    Исполнителям членство выдаёт сам перенос (`ensure_project_member`) — они
    остаются. Наблюдателям-неучастникам членство в ЦЕЛИ перенос не раздаёт:
    доступ в целевой проект — решение его редакторов, а не побочка переноса
    чужой задачи (с 02.09 редактор может подписать человека обратно вручную —
    ручка `POST /tasks/{id}/watchers` выдаёт viewer-членство явно). Поэтому
    неучастников отписываем.

    Побочно отпишутся hub-admin'ы, которым членство не нужно: роль лежит в JWT,
    и по базе её не видно. Fail-closed здесь дешевле, чем гадание — но САМ
    переносящий из этого правила исключён: права редактора в цели у него только
    что проверены, значит задачу он откроет наверняка. Без этой оговорки
    админ, переносящий собственную задачу, отписывался от неё сам, и диалог
    честно предупреждал об этом («отпишется 1 наблюдатель») — предупреждение о
    том, чего делать не следовало.
    """
    watchers = (
        await db.execute(
            select(TaskWatcher.task_id, TaskWatcher.employee_id).where(
                TaskWatcher.task_id.in_(task_ids)
            )
        )
    ).all()
    if not watchers:
        return []
    members = {actor_id}
    members |= set(
        (
            await db.execute(
                select(ProjectMember.employee_id).where(
                    ProjectMember.project_id == target_id
                )
            )
        )
        .scalars()
        .all()
    )
    # Исполнители любой задачи семьи получат членство в проекте — а членство
    # проектное, не задачное.
    members |= set(
        (
            await db.execute(
                select(TaskAssignee.employee_id).where(
                    TaskAssignee.task_id.in_(task_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return [(t, e) for t, e in watchers if e not in members]


async def plan_move(
    db: AsyncSession,
    *,
    task: Task,
    source: Project,
    target: Project,
    principal: Principal,
    stage_id: UUID | None = None,
) -> MovePlan:
    """Посчитать переезд, ничего не записывая. Права проверил вызывающий."""
    await assert_movable(task=task, source=source, target=target, principal=principal)
    if stage_id is not None:
        await get_stage_in_project(db, target.id, stage_id)

    tasks = await _family(db, task)
    ids = [t.id for t in tasks]

    labels_keep, labels_total = await _plan_labels(db, task_ids=ids, target_id=target.id)
    values_keep, values_total = await _plan_values(db, task_ids=ids, target_id=target.id)

    deps = await db.scalar(
        select(func.count())
        .select_from(TaskDependency)
        .where(
            or_(
                and_(
                    TaskDependency.predecessor_id.in_(ids),
                    TaskDependency.successor_id.not_in(ids),
                ),
                and_(
                    TaskDependency.successor_id.in_(ids),
                    TaskDependency.predecessor_id.not_in(ids),
                ),
            )
        )
    )
    shares = await db.scalar(
        select(func.count())
        .select_from(PublicShareToken)
        .where(
            # Таблица БЕЗ RLS — tenant_id обязателен явно (как в delete_project).
            PublicShareToken.tenant_id == principal.tenant_id,
            PublicShareToken.scope == "task",
            PublicShareToken.entity_id.in_(ids),
            _active_token(),
        )
    )
    target_public = bool(
        await db.scalar(
            select(func.count())
            .select_from(PublicShareToken)
            .where(
                PublicShareToken.tenant_id == principal.tenant_id,
                PublicShareToken.scope == "project",
                PublicShareToken.entity_id == target.id,
                _active_token(),
            )
        )
    )

    return MovePlan(
        source=source,
        target=target,
        tasks=tasks,
        stages=await _stage_map(
            db,
            tasks=tasks,
            source_id=source.id,
            target_id=target.id,
            stage_id=stage_id,
        ),
        labels_keep=labels_keep,
        labels_total=labels_total,
        values_keep=values_keep,
        values_total=values_total,
        watchers_drop=await _plan_watchers(
            db, task_ids=ids, target_id=target.id, actor_id=principal.employee_id
        ),
        dependencies_drop=int(deps or 0),
        shares_revoke=int(shares or 0),
        target_public=target_public,
    )


async def apply_move(
    db: AsyncSession, *, plan: MovePlan, principal: Principal
) -> MovePlan:
    """Записать посчитанный переезд. Commit — за вызывающим."""
    ids = [t.id for t in plan.tasks]
    target = plan.target
    old_keys = {t.id: f"{plan.source.key}-{t.seq}" for t in plan.tasks}

    for task in plan.tasks:
        stage_id = plan.stages[task.id]
        task.project_id = target.id
        task.seq = await allocate_task_seq(db, target.id)
        task.stage_id = stage_id
        # Позиция — max+1 внутри (проект, колонка): число из чужой шкалы
        # поставило бы задачу в середину списка на новом месте. Считаем ДО
        # flush'а этой задачи (сессия autoflush=False) — она сама в выборку
        # попасть не должна, а уже переехавшие родственники должны.
        task.position = await next_position(db, target.id, stage_id=stage_id)
        plan.new_keys[task.id] = f"{target.key}-{task.seq}"
        await db.flush()

    # Метки и значения полей: старые назначения снимаем целиком, кладём то, что
    # нашло одноимённую пару в цели.
    await db.execute(
        delete(TaskLabelAssignment).where(TaskLabelAssignment.task_id.in_(ids))
    )
    for task_id, label_id in plan.labels_keep:
        db.add(
            TaskLabelAssignment(
                task_id=task_id, label_id=label_id, tenant_id=principal.tenant_id
            )
        )
    await db.execute(
        delete(TaskCustomFieldValue).where(TaskCustomFieldValue.task_id.in_(ids))
    )
    for task_id, field_id, value in plan.values_keep:
        db.add(
            TaskCustomFieldValue(
                task_id=task_id,
                field_id=field_id,
                tenant_id=principal.tenant_id,
                value=value,
            )
        )

    # Исполнитель обязан сохранить доступ к СВОЕЙ задаче — иначе он узнает о
    # переносе по 403 из пуша.
    assignees = (
        (
            await db.execute(
                select(TaskAssignee.employee_id)
                .where(TaskAssignee.task_id.in_(ids))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for employee_id in assignees:
        await ensure_project_member(
            db,
            project_id=target.id,
            tenant_id=principal.tenant_id,
            employee_id=employee_id,
            added_by=principal.employee_id,
        )

    for task_id, employee_id in plan.watchers_drop:
        await db.execute(
            delete(TaskWatcher).where(
                TaskWatcher.task_id == task_id,
                TaskWatcher.employee_id == employee_id,
            )
        )
        # Переписывать им ссылку бессмысленно: доступа нет ни по старому
        # адресу, ни по новому — строка в «Входящих» вела бы в 403.
        await db.execute(
            delete(Notification).where(
                Notification.employee_id == employee_id,
                Notification.url.like(f"%task={task_id}"),
            )
        )

    await db.execute(
        delete(TaskDependency).where(
            or_(
                and_(
                    TaskDependency.predecessor_id.in_(ids),
                    TaskDependency.successor_id.not_in(ids),
                ),
                and_(
                    TaskDependency.successor_id.in_(ids),
                    TaskDependency.predecessor_id.not_in(ids),
                ),
            )
        )
    )

    for task in plan.tasks:
        # Уведомление переживает переезд, а ссылка в нём несёт СТАРЫЙ проект
        # (`services/notify.py::_task_url`) — «Входящие» открывали бы проект,
        # в котором задачи уже нет.
        await db.execute(
            update(Notification)
            .where(Notification.url.like(f"%task={task.id}"))
            .values(url=f"/projects/{target.id}?task={task.id}")
        )

    # Публичная ссылка выдавалась задаче на её прежнем месте: `_build_task_view`
    # проект не смотрит вовсе, поэтому переезд в личное сделал бы личное
    # публичным в обход `assert_not_personal`. Отзываем — выпустить заново
    # ничего не стоит. tenant_id явно: таблица БЕЗ RLS.
    await db.execute(
        update(PublicShareToken)
        .where(
            PublicShareToken.tenant_id == principal.tenant_id,
            PublicShareToken.scope == "task",
            PublicShareToken.entity_id.in_(ids),
            PublicShareToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )

    for task in plan.tasks:
        await record_activity(
            db,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="moved",
            payload={
                "from_project": plan.source.name,
                "to_project": target.name,
                "from_key": old_keys[task.id],
                "to_key": plan.new_keys[task.id],
            },
        )
    return plan
