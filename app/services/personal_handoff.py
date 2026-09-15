"""Задача в личном пространстве принадлежит тому, кто её делает.

Решение владельца 15.09: «если задачу назначили лично мне — я должен видеть её
в СВОЁМ личном проекте, а не в её, ибо я исполнитель». До этого назначенный
коллега становился гостем в чужом личном пространстве: задача жила у автора, а
исполнитель видел её только в кросс-проектном списке и на странице чужого
«Личного».

Отсюда два правила, и оба действуют ТОЛЬКО внутри личных проектов:

1. **Исполнитель один.** Личное пространство — про одного человека, и «положить
   задачу в два личных» невозможно физически. Попытка назначить двоих — 409.
2. **Назначил другого — задача уезжает к нему.** Полноценным переездом
   (`task_move`), а не сменой `project_id`: у задачи меняется номер, позиция,
   метки и поля пересобираются по одноимённым, активные публичные ссылки
   отзываются. Автор остаётся наблюдателем и получает viewer-членство в цели —
   без него он потерял бы собственную задачу из виду (`personal_task_scope`
   пускает наблюдателя, но карточка требует членства).

Подзадачи переезжать в одиночку не умеют (`assert_movable`), поэтому поручить
подзадачу из личного нельзя — об этом говорим прямо, а не роняем 409 из недр
переноса.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task, TaskAssignee
from app.services.personal_projects import get_personal_project_id
from app.services.project_access import ensure_project_member
from app.services.task_move import apply_move, plan_move


async def _assignee_ids(db: AsyncSession, task_id: UUID) -> list[UUID]:
    return list(
        (
            await db.execute(
                select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task_id)
            )
        )
        .scalars()
        .all()
    )


async def apply_personal_assignee_rules(
    db: AsyncSession, *, task: Task, principal: Principal
) -> Project | None:
    """Позвать ПОСЛЕ изменения состава исполнителей. Commit — за вызывающим.

    Возвращает проект-цель, если задача переехала, иначе None. Для обычных
    проектов не делает ничего.
    """
    project = await db.get(Project, task.project_id)
    if project is None or project.personal_owner_id is None:
        return None

    owner_id = project.personal_owner_id
    assignees = await _assignee_ids(db, task.id)
    if len(assignees) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "В личном пространстве у задачи один исполнитель — "
                "поручите её кому-то одному или перенесите в рабочий проект"
            ),
        )
    if not assignees or assignees[0] == owner_id:
        return None

    target_employee = assignees[0]
    if task.parent_task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Подзадачу нельзя поручить отдельно — она живёт вместе с "
                "родительской задачей"
            ),
        )

    target_id = await get_personal_project_id(db, target_employee)
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Человек ещё ни разу не заходил в Hub — личное пространство "
                "появится после первого входа"
            ),
        )
    target = await db.get(Project, target_id)
    if target is None:  # pragma: no cover — строка есть, раз есть id
        return None

    plan = await plan_move(
        db,
        task=task,
        source=project,
        target=target,
        principal=principal,
        handoff=True,
    )
    await apply_move(db, plan=plan, principal=principal)
    # Членство автору — явным шагом: переезд раздаёт его только исполнителям, а
    # без него автор, оставшись наблюдателем, получил бы 404 на собственную
    # задачу (то же самое делает `POST /api/me/delegate`).
    await ensure_project_member(
        db,
        project_id=target.id,
        tenant_id=principal.tenant_id,
        employee_id=principal.employee_id,
        added_by=principal.employee_id,
    )
    return target
