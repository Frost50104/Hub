"""`GET /api/me/tasks` и `GET /api/me/assigned-by-me` — мои задачи и мои поручения.

Кормит панель «Главной» и страницу `/my`. Фильтры: `done`, `due_window`
(overdue|today|upcoming|all), `include_archived`, `include_personal`.

**«Моё» = назначено мне ИЛИ лежит в моём личном проекте (16.09).** С этой даты
`/my` — единственный вход в личное пространство (страница личного проекта
редиректит сюда), личные задачи идут вперемешку с рабочими, и отдельной секции
«ЛИЧНОЕ» больше нет. Поэтому `include_personal` по умолчанию `True`, а базовый
предикат — общий с `/me/stats` `my_task_scope`.

Окна и задачи БЕЗ срока: `upcoming` их включает (это «всё, что впереди»),
`overdue` и `today` — нет (они про дату). `all` не фильтрует по сроку вовсе.

Архивный проект сюда не попадает (31.08): архив значит «запарковано» — задачи
уходят из личных списков и перестают порождать дедлайнные пуши. Правило одно на
`/me/stats`, `jobs/due_soon.py`, `jobs/overdue.py` и инструменты ассистента,
предикат — `services/projects.py::project_not_archived`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.project import Project
from app.models.stage import ProjectStage
from app.models.task import Task, TaskAssignee
from app.schemas.task import TaskResponse
from app.services.personal_projects import (
    my_task_scope,
    not_my_personal,
    personal_list_scope,
)
from app.services.projects import project_not_archived
from app.services.task_assignees import load_assignees, serialize_with_assignees
from app.services.task_counts import load_row_counts
from app.services.task_recurrence import load_rules, recurrence_info
from app.services.taskdates import (
    display_today,
    overdue_clause,
    start_of_today_utc,
    start_of_tomorrow_utc,
)
from app.services.tasks import apply_done_filter, reject_legacy_status

router = APIRouter(tags=["me-tasks"])

DueWindow = Literal["overdue", "today", "upcoming", "all"]


@router.get("/me/tasks", response_model=list[TaskResponse])
async def list_my_tasks(
    done: bool | None = Query(default=None),
    # LEGACY (0044): см. `_reject_legacy_status` в api/tasks.py.
    status_: str | None = Query(default=None, alias="status"),
    due_window: DueWindow | None = Query(default=None),
    # «Архивное вообще»: и архивные ЗАДАЧИ, и задачи архивных ПРОЕКТОВ. Флаг
    # один, потому что смысл один — «покажи убранное»; клиент его не шлёт
    # (вход в архив — пункт сайдбара «Архив», а не фильтр этого списка).
    include_archived: bool = Query(default=False),
    # Дефолт перевёрнут 16.09: личные задачи — часть «моего». `False` остаётся
    # входом для тех, кому нужен только рабочий срез, и для вчерашних
    # PWA-бандлов, у которых секция «ЛИЧНОЕ» ещё на экране (они параметр не
    # шлют, но их спасает клиентская страховка `excludeProject`). Задачи из
    # ЧУЖОГО личного, назначенные мне, флаг не трогает никогда — это обычная
    # работа.
    include_personal: bool = Query(default=True),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    reject_legacy_status(status_)
    # EXISTS, а не JOIN на task_assignees: JOIN размножил бы задачу по числу
    # исполнителей и дал дубли в списке. Семантика — «я СРЕДИ исполнителей».
    stmt = (
        select(Task, Project.key, ProjectStage.name, _is_personal_col())
        # key проекта — для бейджа «KEY-42» в кросс-проектном списке,
        # имя колонки — единственный признак прогресса в чужом проекте.
        .join(Project, Project.id == Task.project_id)
        # LEFT JOIN обязателен: у задачи может не быть статуса (0046), и INNER
        # выкинул бы её из «Моих задач» целиком — вместе с назначением.
        .outerjoin(ProjectStage, ProjectStage.id == Task.stage_id)
        .where(my_task_scope(principal.employee_id))
        .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
    )
    if not include_archived:
        # Два РАЗНЫХ архива в одной строке: задачи и её проекта. Проект — через
        # предикат `project_not_archived()`, потому что правило кросс-проектное
        # и живёт ещё в `/me/stats`, двух cron-джобах и инструментах ассистента;
        # джойн на `projects` здесь уже есть (выше, ради `Project.key`), так что
        # условие бесплатное.
        stmt = stmt.where(Task.archived_at.is_(None), project_not_archived())
    if not include_personal:
        stmt = stmt.where(not_my_personal(principal.employee_id))
    stmt = apply_done_filter(stmt, done)

    # Окна — по КАЛЕНДАРНЫМ дням display tz (services/taskdates.py), не по
    # now(): задача со сроком сегодня после полудня — в «Сегодня» и
    # «Предстоит», а не в «Просрочено» (ОС тестировщика 2026-08).
    now = datetime.now(UTC)
    if due_window == "overdue":
        stmt = stmt.where(overdue_clause(now))
    elif due_window == "today":
        # «Сегодня» = просроченные (не done) + всё со сроком сегодня
        # (решение владельца 2026-08-21, как в Asana).
        stmt = stmt.where(
            Task.due_at < start_of_tomorrow_utc(now),
            or_(Task.done.is_(False), Task.due_at >= start_of_today_utc(now)),
        )
    elif due_window == "upcoming":
        # Бессрочные — тоже «предстоит» (ОС 15.09: «в мои задачи не отображаются
        # задачи без конкретного срока»). Срока нет у 75% назначенных задач на
        # проде, и окно прятало их целиком: `NULL >= ts` даёт NULL, строка не
        # проходит WHERE. Условие пишется ЯВНЫМ `or_`, а не надеется на
        # сравнение. Что отсечение было непреднамеренным, видно по сортировке
        # этого же запроса — `nulls_last()` место для них уже держит.
        #
        # `overdue` и `today` остаются как есть: они про дату, и задача без
        # срока ни просроченной, ни «на сегодня» быть не может.
        stmt = stmt.where(
            or_(Task.due_at >= start_of_today_utc(now), Task.due_at.is_(None)),
            Task.done.is_(False),
        )

    return await _serialize_rows(db, (await db.execute(stmt)).all(), now=now)


def _is_personal_col():
    """`project_is_personal` для строки кросс-проектного списка.

    Считаем на сервере, а не «нет в списке проектов» на клиенте: у эвристики
    есть ложноположительные — на проде 19 живых задач лежат в ОБЫЧНЫХ
    проектах, где их автор больше не участник, и такая строка получила бы
    подпись «личное коллеги». Владельца при этом наружу по-прежнему не отдаём —
    только факт.
    """
    return Project.personal_owner_id.is_not(None).label("project_is_personal")


async def _serialize_rows(
    db: AsyncSession, rows, *, now: datetime
) -> list[TaskResponse]:
    """Строки `(Task, project.key, stage.name, is_personal)` → ответ.

    Один хвост на обе кросс-проектные ручки: три копии сериализации (была уже
    вторая — в `me_delegate.py`) разъехались бы на первой же новой колонке.

    Счётчики комментариев и вложений заполняются ЗДЕСЬ (16.09). Раньше их знал
    только `GET /projects/{id}/tasks`, и на «Моих задачах» личные строки были
    «богаче» рабочих — известный разнобой из `docs/tech-debt/open.md`. После
    слияния экрана он стал бы заметнее: одна и та же личная задача показывала
    бы чип комментариев на вкладке «Личные» (она ходит в ручку проекта) и не
    показывала на соседней.
    """
    ids = [task.id for task, _, _, _ in rows]
    by_task = await load_assignees(db, ids)
    counts = await load_row_counts(db, ids)
    rules = await load_rules(db, ids)
    today = display_today(now)
    out: list[TaskResponse] = []
    for task, project_key, stage_name, is_personal in rows:
        data = serialize_with_assignees(task, by_task.get(task.id, []))
        data.recurrence = recurrence_info(rules.get(task.id), today=today)
        data.project_key = project_key
        data.stage_name = stage_name
        data.project_is_personal = bool(is_personal)
        c = counts.get(task.id)
        if c is not None:
            data.comment_count = c.comments
            data.attachment_count = c.attachments
            data.blocker_count = c.blockers
        out.append(data)
    return out


@router.get("/me/assigned-by-me", response_model=list[TaskResponse])
async def list_assigned_by_me(
    include_archived: bool = Query(default=False),
    done: bool | None = Query(default=False),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    """«Назначенные мной» — что я поручил другим, по ВСЕМ проектам.

    Поглощает прежнюю секцию «Я поставил» (`GET /me/delegated`), которая видела
    только поручения в чужое личное: на проде это 2 задачи из 37. Сама ручка
    остаётся жить до протухания PWA-бандлов — см. её докстринг.

    «Назначил другим», а не «создал»: без условия «кто-то, кроме меня, среди
    исполнителей» сюда приехали бы все мои собственные задачи (у самого
    загруженного человека — 38 строк, уже стоящих в соседних вкладках).

    Копии повторяющихся задач НЕ исключаем, хотя соседний `my_created_stmt` в
    `/me/stats` их режет. Там это верно — он считает «завёл руками за период»;
    здесь вредно: копия несёт `created_by` автора серии, а оригинал к этому
    моменту закрыт, и фильтр спрятал бы единственную живую строку цепочки.
    """
    me = principal.employee_id
    stmt = (
        select(Task, Project.key, ProjectStage.name, _is_personal_col())
        .join(Project, Project.id == Task.project_id)
        .outerjoin(ProjectStage, ProjectStage.id == Task.stage_id)
        .where(
            Task.created_by == me,
            select(TaskAssignee.task_id)
            .where(TaskAssignee.task_id == Task.id, TaskAssignee.employee_id != me)
            .exists(),
            # Членство + правило чужого личного. Без него список показывал бы
            # строки, которые 404-ят при клике (`/me/tasks` этим болеет и
            # сегодня — чинится отдельной задачей, там смена поведения).
            personal_list_scope(me),
        )
        .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Task.archived_at.is_(None), project_not_archived())
    stmt = apply_done_filter(stmt, done)
    return await _serialize_rows(db, (await db.execute(stmt)).all(), now=datetime.now(UTC))
