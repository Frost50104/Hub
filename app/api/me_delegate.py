"""Поручить задачу человеку ЛИЧНО: она живёт в его личном пространстве.

Запрос владельца 15.09: «надо добавить возможность создавать задачу прямо в
личные задачи исполнителю, чтобы её видел только исполнитель и автор, но автор
не видел другие личные задачи исполнителя».

**Приватность НЕ изобретается заново** — она уже построена под этот сценарий:

- `personal_task_scope` показывает НЕвладельцу только задачи, где он
  исполнитель ИЛИ наблюдатель. Автор становится наблюдателем при создании
  (`create_task_record(watch_creator=True)`), поэтому видит ровно свою задачу и
  ничего больше;
- агрегаты чужого личного — 403 (`assert_full_project_access`), сам проект
  скрыт из всех списков (`not_personal`), а `GET /projects/{id}` не отдаёт
  гостю счётчики (см. `projects.py::_task_counts`);
- поиск, комментарии и ассистент режут чужое личное предикатом
  `personal_visible_to` — его НЕ трогаем (он же защищает от выгребания чужих
  заметок во внешнюю LLM), поэтому автору дана секция «Я поставил».

Ручка узкая и отдельная — по образцу `POST /api/feedback`: общий
`POST /projects/{id}/tasks` стоит на `require_project_role(owner|editor)`, и
посторонний в чужом личном получает 404. Ослаблять тот гейт нельзя: он же
охраняет обычные проекты.

Поручить можно ЛЮБОМУ сотруднику (решение владельца) — защита от мусора в
чужом inbox'е сводится к rate-limit и к тому, что автор виден в задаче.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.project import Project
from app.models.stage import ProjectStage
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse
from app.services.personal_projects import get_personal_project_id
from app.services.project_access import ensure_project_member
from app.services.projects import project_not_archived
from app.services.task_assignees import (
    apply_assignee_side_effects,
    assert_assignees_in_tenant,
    load_assignees,
    serialize_with_assignees,
    set_task_assignees,
)
from app.services.task_recurrence import load_rules, recurrence_info
from app.services.taskdates import display_today
from app.services.tasks import create_task_record

router = APIRouter(tags=["me-delegate"])


class DelegateCreate(BaseModel):
    """Тело поручения. `extra="forbid"` — как у TaskCreate (0045)."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    due_at: datetime | None = None


@router.post(
    "/me/delegate", response_model=TaskResponse, status_code=status.HTTP_201_CREATED
)
async def delegate_personal_task(
    body: DelegateCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    if body.employee_id == principal.employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Себе задачу заводите обычным способом — в «Личном»",
        )
    # Тот же валидатор, что у исполнителей: уволенный в auth сюда не пройдёт.
    await assert_assignees_in_tenant(db, [body.employee_id])

    project_id = await get_personal_project_id(db, body.employee_id)
    if project_id is None:
        # Личное пространство заводится при ПЕРВОМ входе в Hub, и вместе с ним
        # — задача-инструкция. Создавать проект за человека мы не будем:
        # инструкцию он тогда не получит никогда (она привязана к моменту
        # создания), а задача всё равно ждала бы его первого входа. На проде
        # так «недоступны» 53 человека из 227 — все, кто ни разу не заходил.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Человек ещё ни разу не заходил в Hub — личное пространство "
                "появится после первого входа"
            ),
        )

    task = await create_task_record(
        db,
        principal=principal,
        project_id=project_id,
        body=TaskCreate(
            title=body.title,
            description=body.description,
            due_at=body.due_at,
        ),
        # watch_creator=True (дефолт) — подписка автора это и есть его доступ:
        # `personal_task_scope` пускает наблюдателя к ЭТОЙ задаче и ни к одной
        # другой. В отличие от обратной связи, где автор сознательно не
        # подписывается, здесь без подписки фича теряет смысл.
    )
    # Членство — отдельным шагом: без него `get_task`, комментарии и вложения
    # ответили бы 404 (существование чужого личного скрыто). Роль viewer, как у
    # обратной связи: править задачу автору разрешает узкое правило в
    # `api/tasks.py`, а не роль в проекте.
    await ensure_project_member(
        db,
        project_id=project_id,
        tenant_id=principal.tenant_id,
        employee_id=principal.employee_id,
        added_by=principal.employee_id,
    )
    await db.flush()
    # Исполнитель — отдельным шагом ради `notify=True`: внутри create побочки
    # исполнителя намеренно молчат, и получатель не узнал бы о поручении.
    diff = await set_task_assignees(
        db,
        task=task,
        employee_ids=[body.employee_id],
        actor_id=principal.employee_id,
    )
    await apply_assignee_side_effects(
        db,
        task=task,
        diff=diff,
        actor_id=principal.employee_id,
        actor_name=principal.full_name or principal.email,
        notify=True,
        record=True,
    )
    await db.commit()
    await db.refresh(task)

    assignees = await load_assignees(db, [task.id])
    rules = await load_rules(db, [task.id])
    data = serialize_with_assignees(task, assignees.get(task.id, []))
    data.recurrence = recurrence_info(rules.get(task.id), today=display_today())
    return data


@router.get("/me/delegated", response_model=list[TaskResponse])
async def list_delegated(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    """DEPRECATED (16.09): поглощена `GET /me/assigned-by-me`.

    Новая ручка показывает всё, что я поручил другим по ВСЕМ проектам, а не
    только в чужое личное — на проде это 37 задач против 2. Эта остаётся жить,
    пока не протухнут PWA-бандлы: `registerType: 'prompt'`, обновление
    принимает человек, и шипнутый бандл зовёт именно её. Снимать — отдельной
    правкой, вместе с `useDelegated` на клиенте.

    Строгим подмножеством новой она при этом НЕ является: здесь нет условия
    «кто-то среди исполнителей», поэтому поручение со снятым исполнителем
    видно тут и не видно там. Расхождение осознанное — новая ручка про
    «назначил другому», эта про «завёл в чужом личном».

    Секция «Я поставил»: что я положил людям в личное и это ещё не закрыто.

    Иначе автор свою же задачу не найдёт: `personal_visible_to` («не личный ИЛИ
    МОЙ личный») режет её и в поиске, и в комментариях, и у ассистента, а в
    `/me/tasks` он не исполнитель. Остаются уведомления и прямая ссылка —
    этого мало, поэтому отдельная выборка.

    Скоуп задан самим условием: `created_by = я` в ЧУЖОМ личном проекте — это
    ровно те задачи, которые я и завёл, чужих заметок сюда не попадает.
    """
    rows = (
        await db.execute(
            select(Task, Project.key, ProjectStage.name)
            .join(Project, Project.id == Task.project_id)
            .outerjoin(ProjectStage, ProjectStage.id == Task.stage_id)
            .where(
                Task.created_by == principal.employee_id,
                Project.personal_owner_id.is_not(None),
                Project.personal_owner_id != principal.employee_id,
                Task.done.is_(False),
                Task.archived_at.is_(None),
                project_not_archived(),
            )
            .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
        )
    ).all()
    ids = [task.id for task, _, _ in rows]
    by_task = await load_assignees(db, ids)
    rules = await load_rules(db, ids)
    today = display_today()
    out: list[TaskResponse] = []
    for task, project_key, stage_name in rows:
        data = serialize_with_assignees(task, by_task.get(task.id, []))
        data.recurrence = recurrence_info(rules.get(task.id), today=today)
        data.project_key = project_key
        data.stage_name = stage_name
        out.append(data)
    return out
