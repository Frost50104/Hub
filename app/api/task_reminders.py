"""Личные напоминания по задаче (0062): `GET/POST/DELETE /tasks/{id}/reminders`.

Напоминание — только СЕБЕ (решение владельца 24.09), поэтому права на правку
не нужны: ставит любой, кто видит задачу, включая viewer'а-исполнителя, —
это личная настройка, как колокольчик «следить», а не правка задачи.

Ручки на обычном `get_db`, НЕ `get_db_template_page`: задача шаблона невидима
(404), напоминаний в шаблоне не бывает, реестр ручек шаблона не меняется.
Правила и тексты состояний — `services/task_reminders.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from signaris_auth import Principal
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.notification import NotificationPreferences
from app.models.project import Project
from app.models.push_subscription import PushSubscription
from app.models.task import Task, TaskAssignee, TaskReminder, TaskWatcher
from app.services.notification_prefs import (
    normalize_prefs,
    should_send_inapp,
    should_send_push,
)
from app.services.personal_projects import require_task_access
from app.services.project_access import get_my_role, is_hub_admin
from app.services.push_sender import vapid_status
from app.services.task_reminders import (
    KIND,
    MAX_HORIZON,
    MAX_PER_TASK,
    TaskFacts,
    anchor_moment,
    item_state,
    may_receive,
)

router = APIRouter(tags=["tasks"])

# Момент, «уже прошедший» для формы: человек мог выбрать «через час» минуту
# назад, а запрос шёл по медленной сети.
_PAST_TOLERANCE = timedelta(seconds=60)


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: Literal["at", "due", "due_day", "start", "start_day"]
    offset_minutes: int = Field(default=0, ge=0, le=10080)
    # Только у `at`: момент, выбранный руками.
    fire_at: datetime | None = None


class ReminderItem(BaseModel):
    id: UUID
    anchor: str
    offset_minutes: int
    # Когда придёт (взведено); None — сработало или «спит».
    fire_at: datetime | None
    state: Literal["armed", "fired", "no_date", "passed", "done", "archived"]
    # Для сработавшего правила — когда пришло.
    fired_at: datetime | None = None


class ReminderDelivery(BaseModel):
    """Честная подсказка в карточке: куда реально придёт напоминание."""

    push_devices: int
    push_on: bool
    inapp_on: bool


class RemindersResponse(BaseModel):
    items: list[ReminderItem]
    delivery: ReminderDelivery


def _require_enabled() -> None:
    if not get_settings().task_reminders_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")


async def _task_and_access(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> tuple[Task, Project, bool]:
    """Задача, проект и «поставлено hub-admin'ом без членства» (`via_admin`)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    project, _role = await require_task_access(db, task, principal)
    via_admin = is_hub_admin(principal) and (
        await get_my_role(db, project.id, principal.employee_id) is None
    )
    return task, project, via_admin


async def _delivery(db: AsyncSession, employee_id: UUID) -> ReminderDelivery:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.push_freshness_days)
    devices = (
        await db.execute(
            select(func.count(PushSubscription.id)).where(
                PushSubscription.employee_id == employee_id,
                PushSubscription.last_seen_at > cutoff,
            )
        )
    ).scalar_one()
    raw = (
        await db.execute(
            select(NotificationPreferences.prefs).where(
                NotificationPreferences.employee_id == employee_id
            )
        )
    ).scalar_one_or_none()
    prefs = normalize_prefs(raw)
    return ReminderDelivery(
        push_devices=int(devices),
        push_on=should_send_push(prefs, KIND) and vapid_status() == "ok",
        inapp_on=should_send_inapp(prefs, KIND),
    )


async def _response(
    db: AsyncSession, task: Task, project: Project, employee_id: UUID
) -> RemindersResponse:
    now = datetime.now(UTC)
    facts = TaskFacts.of(task, project)
    rows = (
        await db.execute(
            select(TaskReminder)
            .where(TaskReminder.task_id == task.id, TaskReminder.employee_id == employee_id)
            .order_by(TaskReminder.created_at, TaskReminder.id)
        )
    ).scalars().all()
    items: list[ReminderItem] = []
    for r in rows:
        state, fire_at, fired_at = item_state(
            anchor=r.anchor,
            offset_minutes=r.offset_minutes,
            facts=facts,
            fired_anchor_at=r.fired_anchor_at,
            fire_at=r.fire_at,
            now=now,
        )
        items.append(
            ReminderItem(
                id=r.id,
                anchor=r.anchor,
                offset_minutes=r.offset_minutes,
                fire_at=fire_at,
                state=state,
                fired_at=fired_at,
            )
        )
    return RemindersResponse(items=items, delivery=await _delivery(db, employee_id))


@router.get("/tasks/{task_id}/reminders", response_model=RemindersResponse)
async def list_task_reminders(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> RemindersResponse:
    _require_enabled()
    task, project, _via_admin = await _task_and_access(db, task_id, principal)
    return await _response(db, task, project, principal.employee_id)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


@router.post(
    "/tasks/{task_id}/reminders",
    response_model=RemindersResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_reminder(
    task_id: UUID,
    body: ReminderCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> RemindersResponse:
    _require_enabled()
    await enforce_rate_limit(
        bucket="task:remind", employee_id=str(principal.employee_id), limit=30, window_sec=60
    )
    task, project, via_admin = await _task_and_access(db, task_id, principal)
    # Всё, что тик молча выбросил бы, — честный отказ сразу, а не тост
    # «Напомню…» про напоминание, которое не придёт.
    if project.archived_at is not None:
        raise _conflict("Проект в архиве — напоминания из него не приходят")
    if task.archived_at is not None:
        raise _conflict("Задача в архиве — напоминание не придёт")
    if task.done:
        raise _conflict("Задача выполнена — напоминание не придёт")
    me = principal.employee_id
    involved = (
        await db.execute(
            select(TaskAssignee.task_id)
            .where(TaskAssignee.task_id == task.id, TaskAssignee.employee_id == me)
            .union(
                select(TaskWatcher.task_id).where(
                    TaskWatcher.task_id == task.id, TaskWatcher.employee_id == me
                )
            )
        )
    ).first() is not None
    if not may_receive(
        employee_id=me,
        deleted=False,
        personal_owner_id=project.personal_owner_id,
        is_member=await get_my_role(db, project.id, me) is not None,
        via_admin=via_admin,
        involved=involved,
    ):
        raise _conflict("Напоминание здесь не сработает — у вас нет постоянного доступа к задаче")

    existing = (
        await db.execute(
            select(func.count(TaskReminder.id)).where(
                TaskReminder.task_id == task.id, TaskReminder.employee_id == me
            )
        )
    ).scalar_one()
    if existing >= MAX_PER_TASK:
        raise _conflict(f"Не больше {MAX_PER_TASK} напоминаний на одну задачу")

    now = datetime.now(UTC)
    if body.anchor == "at":
        if body.fire_at is None:
            raise _unprocessable("Укажите время напоминания")
        # Минута — единица выбора; заодно двойной клик попадает в UNIQUE.
        fire_at = body.fire_at.astimezone(UTC).replace(second=0, microsecond=0)
        offset = 0
    else:
        if body.fire_at is not None:
            raise _unprocessable("Время задаётся сроком задачи, а не вручную")
        try:
            anchor_at = anchor_moment(body.anchor, TaskFacts.of(task, project))
        except OverflowError:
            raise _unprocessable("У задачи некорректная дата") from None
        if anchor_at is None:
            raise _unprocessable(
                "У задачи нет даты начала"
                if body.anchor.startswith("start")
                else "У задачи нет срока"
            )
        offset = body.offset_minutes
        try:
            fire_at = anchor_at - timedelta(minutes=offset)
        except OverflowError:
            raise _unprocessable("У задачи некорректная дата") from None
    if fire_at < now - _PAST_TOLERANCE:
        raise _unprocessable("Это время уже прошло")
    if fire_at > now + MAX_HORIZON:
        raise _unprocessable("Напоминание ставится не дальше чем на год вперёд")

    await db.execute(
        pg_insert(TaskReminder)
        .values(
            id=uuid4(),
            tenant_id=task.tenant_id,
            task_id=task.id,
            employee_id=me,
            anchor=body.anchor,
            offset_minutes=offset,
            fire_at=max(fire_at, now),
            via_admin=via_admin,
        )
        # Дубль (двойной клик, повтор запроса) — существующая строка.
        .on_conflict_do_nothing()
    )
    await db.commit()
    return await _response(db, task, project, me)


@router.delete(
    "/tasks/{task_id}/reminders/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_task_reminder(
    task_id: UUID,
    reminder_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Идемпотентно: гонка с тиком, который разовое уже отправил и удалил, —
    не ошибка для человека, нажавшего «Удалить»."""
    _require_enabled()
    await _task_and_access(db, task_id, principal)
    await db.execute(
        delete(TaskReminder).where(
            TaskReminder.id == reminder_id,
            TaskReminder.task_id == task_id,
            TaskReminder.employee_id == principal.employee_id,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
