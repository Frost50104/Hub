"""Project dashboard stats (Phase 4.6).

`GET /api/projects/{project_id}/stats` returns a single JSON payload with
all of the data the ProjectDashboard.tsx page needs — one round-trip is
enough so the UI can render every card in parallel.

Aggregates exposed:
- `done_breakdown` / `priority_breakdown` — `{value: count}` maps.
- `completed_trend` — list of `{day: YYYY-MM-DD, count: int}` for the
  last 30 days (zero-padded so the chart x-axis is continuous).
- `overdue_count` — tasks with `due_at` before today and `NOT done` (0044).
- `workload` — top assignees by active (non-done, non-archived) count.
- `custom_field_stats` — per field:
   - number → {sum, avg, min, max, count}
   - select/multi_select → {options: [{id, label, count}]}
   - other types omitted (nothing useful to report).

All counts respect RLS via `tenant_scoped_session(principal.tenant_id)`.
Viewer+ is required on the project (same gate as `/tasks`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import (
    Double,
    Integer,
    String,
    Text,
    and_,
    bindparam,
    cast,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_db, require_auth, require_auth_any
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee
from app.services.personal_projects import (
    assert_full_project_access,
)
from app.services.project_access import require_project_role
from app.services.task_assignees import assignee_exists, has_no_assignees
from app.services.taskdates import (
    display_today,
    start_of_today_utc,
    start_of_tomorrow_utc,
    start_of_window_utc,
)

router = APIRouter(tags=["stats"])

_TREND_DAYS = 30
_WORKLOAD_TOP = 10

# Личная статистика на «Главной»: длинное окно и короткое.
_MY_DAYS = 30
_MY_SHORT_DAYS = 7


class TrendPoint(BaseModel):
    day: date
    count: int


class WorkloadEntry(BaseModel):
    employee_id: UUID | None
    full_name: str | None
    email: str | None
    active_count: int
    done_count: int
    # Просроченные у исполнителя (дашборд редизайна, колонка «Просрочено»).
    # Дефолт 0 — старые клиенты поля не ждут, новые читают.
    overdue_count: int = 0


class NumberStats(BaseModel):
    sum: float | None
    avg: float | None
    min: float | None
    max: float | None
    count: int


class OptionCount(BaseModel):
    id: str
    label: str
    count: int


class SelectStats(BaseModel):
    options: list[OptionCount]


class CustomFieldStat(BaseModel):
    field_id: UUID
    name: str
    type: str
    number: NumberStats | None = None
    select: SelectStats | None = None


class ProjectStatsResponse(BaseModel):
    # Состояние задач: {"done": N, "open": M} (0044 — вместо четырёх статусов).
    done_breakdown: dict[str, int]
    # Срез по колонкам доски: ключ — id колонки строкой, значение — счётчик.
    # Имя колонки фронт берёт из /stages (один запрос на проект, кэш).
    stage_breakdown: dict[str, int] = {}
    priority_breakdown: dict[str, int]
    completed_trend: list[TrendPoint]
    overdue_count: int
    workload: list[WorkloadEntry]
    custom_field_stats: list[CustomFieldStat]
    total_active: int
    total_archived: int


async def _status_or_priority_breakdown(
    session: AsyncSession, project_id: UUID, column
) -> dict[str, int]:
    rows = await session.execute(
        select(column, func.count(Task.id))
        .where(Task.project_id == project_id, Task.archived_at.is_(None))
        .group_by(column)
    )
    return {str(label): int(count) for label, count in rows.all()}


async def _completed_trend(
    session: AsyncSession, project_id: UUID
) -> list[TrendPoint]:
    """Tasks completed per day for the last `_TREND_DAYS`. Zero-padded so
    the front-end chart has a continuous x-axis even on quiet days.
    """
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=_TREND_DAYS - 1)
    start_dt = datetime.combine(start_date, time(0, 0, 0), tzinfo=UTC)
    rows = await session.execute(
        select(
            func.date_trunc("day", Task.completed_at).label("day"),
            func.count(Task.id),
        )
        .where(
            Task.project_id == project_id,
            Task.completed_at.is_not(None),
            Task.completed_at >= start_dt,
        )
        .group_by(text("day"))
        .order_by(text("day"))
    )
    counts: dict[date, int] = {}
    for raw_day, count in rows.all():
        if raw_day is None:
            continue
        counts[raw_day.date()] = int(count)
    out: list[TrendPoint] = []
    for i in range(_TREND_DAYS):
        d = start_date + timedelta(days=i)
        out.append(TrendPoint(day=d, count=counts.get(d, 0)))
    return out


async def _overdue_count(session: AsyncSession, project_id: UUID) -> int:
    # Просрочено = день срока раньше сегодняшнего (display tz) — см. taskdates.
    today_start = start_of_today_utc()
    row = await session.execute(
        select(func.count(Task.id)).where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            Task.done.is_(False),
            Task.due_at.is_not(None),
            Task.due_at < today_start,
        )
    )
    return int(row.scalar_one())


_ACTIVE_SUM = func.sum(
    cast(and_(Task.archived_at.is_(None), Task.done.is_(False)), Integer)
).label("active_count")
_DONE_SUM = func.sum(cast(Task.done, Integer)).label("done_count")


def _overdue_sum(now: datetime):
    """Просроченные (тот же критерий, что `_overdue_count`): активные, не
    закрытые, день срока раньше сегодняшнего. Считается в том же фан-ауте по
    исполнителям — задача на двоих горит у обоих."""
    return func.sum(
        cast(
            and_(
                Task.archived_at.is_(None),
                Task.done.is_(False),
                Task.due_at < start_of_today_utc(now),
            ),
            Integer,
        )
    ).label("overdue_count")


async def _workload(
    session: AsyncSession, project_id: UUID
) -> list[WorkloadEntry]:
    """Загрузка по исполнителям + бакет «без исполнителя» (employee_id=None).

    С множественными исполнителями (0034) фан-аут JOIN'а здесь НАМЕРЕННЫЙ:
    задача на двоих честно считается обоим — это семантика загрузки, а не
    пересчёт задач. Следствие: сумма по строкам БОЛЬШЕ числа задач проекта.

    INNER JOIN отбрасывает задачи без исполнителей, поэтому бакет «без
    исполнителя» считается отдельным запросом и склеивается ПОСЛЕ, иначе
    limit(_WORKLOAD_TOP) мог бы его отсечь.
    """
    now = datetime.now(UTC)
    overdue_sum = _overdue_sum(now)
    rows = await session.execute(
        select(
            TaskAssignee.employee_id,
            ShadowUser.full_name,
            ShadowUser.email,
            _ACTIVE_SUM,
            _DONE_SUM,
            overdue_sum,
        )
        .select_from(Task)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskAssignee.employee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Task.project_id == project_id)
        .group_by(TaskAssignee.employee_id, ShadowUser.full_name, ShadowUser.email)
        .order_by(text("active_count DESC NULLS LAST"))
        .limit(_WORKLOAD_TOP)
    )
    out = [
        WorkloadEntry(
            employee_id=row.employee_id,
            full_name=row.full_name,
            email=row.email,
            active_count=int(row.active_count or 0),
            done_count=int(row.done_count or 0),
            overdue_count=int(row.overdue_count or 0),
        )
        for row in rows.all()
    ]

    unassigned = (
        await session.execute(
            select(_ACTIVE_SUM, _DONE_SUM, overdue_sum).where(
                Task.project_id == project_id, has_no_assignees()
            )
        )
    ).first()
    if unassigned is not None and (unassigned.active_count or unassigned.done_count):
        out.append(
            WorkloadEntry(
                employee_id=None,
                full_name=None,
                email=None,
                active_count=int(unassigned.active_count or 0),
                done_count=int(unassigned.done_count or 0),
                overdue_count=int(unassigned.overdue_count or 0),
            )
        )
        out.sort(key=lambda e: e.active_count, reverse=True)
        out = out[:_WORKLOAD_TOP]
    return out


async def _custom_field_stats(
    session: AsyncSession, project_id: UUID
) -> list[CustomFieldStat]:
    defs = (
        await session.execute(
            select(CustomFieldDefinition)
            .where(CustomFieldDefinition.project_id == project_id)
            .order_by(CustomFieldDefinition.position)
        )
    ).scalars().all()

    if not defs:
        return []

    number_ids = [d.id for d in defs if d.type == "number"]
    select_ids = [d.id for d in defs if d.type == "select"]
    multi_ids = [d.id for d in defs if d.type == "multi_select"]

    # ─── Bulk number aggregates, grouped by field_id (1 query for all). ───
    # `jsonb_typeof = 'number'` skips any value that somehow isn't numeric
    # despite the field type — defensive. `count` is labelled `cnt` to avoid
    # clashing with the tuple `.count` method on Row.
    num_by_field: dict[UUID, Any] = {}
    if number_ids:
        cast_f = cast(TaskCustomFieldValue.value, Double)
        num_rows = await session.execute(
            select(
                TaskCustomFieldValue.field_id,
                func.sum(cast_f).label("sum"),
                func.avg(cast_f).label("avg"),
                func.min(cast_f).label("min"),
                func.max(cast_f).label("max"),
                func.count(TaskCustomFieldValue.task_id).label("cnt"),
            )
            .join(Task, Task.id == TaskCustomFieldValue.task_id)
            .where(
                Task.project_id == project_id,
                Task.archived_at.is_(None),
                TaskCustomFieldValue.field_id.in_(number_ids),
                text("jsonb_typeof(task_custom_field_values.value) = 'number'"),
            )
            .group_by(TaskCustomFieldValue.field_id)
        )
        num_by_field = {row.field_id: row for row in num_rows.all()}

    # ─── Bulk option counts for select + multi_select, grouped by field_id. ───
    # A field is either select OR multi_select, never both, so one dict keyed
    # by field_id has no collisions.
    options_by_field: dict[UUID, list[tuple[str, int]]] = {}
    if select_ids:
        opt_id_col = cast(TaskCustomFieldValue.value, Text).label("opt_id")
        sel_rows = await session.execute(
            select(
                TaskCustomFieldValue.field_id,
                opt_id_col,
                func.count(TaskCustomFieldValue.task_id).label("cnt"),
            )
            .join(Task, Task.id == TaskCustomFieldValue.task_id)
            .where(
                Task.project_id == project_id,
                Task.archived_at.is_(None),
                TaskCustomFieldValue.field_id.in_(select_ids),
                text("jsonb_typeof(task_custom_field_values.value) = 'string'"),
            )
            .group_by(TaskCustomFieldValue.field_id, text("opt_id"))
        )
        for row in sel_rows.all():
            options_by_field.setdefault(row.field_id, []).append(
                (str(row.opt_id).strip('"'), int(row.cnt))
            )
    if multi_ids:
        # multi_select — expand each JSONB array, group by (field_id, element).
        multi_stmt = text(
            "SELECT tcfv.field_id AS field_id, v.elem AS opt_id, COUNT(*) AS cnt "
            "FROM task_custom_field_values tcfv "
            "JOIN tasks t ON t.id = tcfv.task_id "
            ", jsonb_array_elements_text(tcfv.value) v(elem) "
            "WHERE tcfv.field_id IN :fids "
            "AND t.project_id = :pid "
            "AND t.archived_at IS NULL "
            "AND jsonb_typeof(tcfv.value) = 'array' "
            "GROUP BY tcfv.field_id, v.elem"
        ).bindparams(bindparam("fids", expanding=True))
        multi_rows = await session.execute(
            multi_stmt,
            {"fids": [str(i) for i in multi_ids], "pid": str(project_id)},
        )
        for row in multi_rows.all():
            options_by_field.setdefault(UUID(str(row.field_id)), []).append(
                (str(row.opt_id).strip('"'), int(row.cnt))
            )

    out: list[CustomFieldStat] = []
    for d in defs:
        if d.type == "number":
            row = num_by_field.get(d.id)
            s = row.sum if row else None
            a = row.avg if row else None
            mn = row.min if row else None
            mx = row.max if row else None
            cnt = row.cnt if row else 0
            out.append(
                CustomFieldStat(
                    field_id=d.id,
                    name=d.name,
                    type=d.type,
                    number=NumberStats(
                        sum=float(s) if s is not None else None,
                        avg=float(a) if a is not None else None,
                        min=float(mn) if mn is not None else None,
                        max=float(mx) if mx is not None else None,
                        count=int(cnt or 0),
                    ),
                )
            )
        elif d.type in ("select", "multi_select"):
            option_lookup = {str(opt.get("id")): str(opt.get("label", opt.get("id")))
                             for opt in (d.options or [])}
            options_by_id: dict[str, OptionCount] = {}
            for opt_id, count in options_by_field.get(d.id, []):
                label = option_lookup.get(opt_id, opt_id)
                options_by_id[opt_id] = OptionCount(
                    id=opt_id, label=label, count=count
                )
            out.append(
                CustomFieldStat(
                    field_id=d.id,
                    name=d.name,
                    type=d.type,
                    select=SelectStats(options=list(options_by_id.values())),
                )
            )
    return out


@router.get(
    "/projects/{project_id}/stats", response_model=ProjectStatsResponse
)
async def get_stats(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectStatsResponse:
    project, _ = await require_project_role(db, project_id, principal)
    assert_full_project_access(project, principal)

    done_breakdown = await _status_or_priority_breakdown(db, project_id, Task.done)
    # Ключи булева среза приходят как "True"/"False" — приводим к контракту.
    done_breakdown = {
        "done": done_breakdown.get("True", 0),
        "open": done_breakdown.get("False", 0),
    }
    stage_breakdown = await _status_or_priority_breakdown(db, project_id, Task.stage_id)
    priority_breakdown = await _status_or_priority_breakdown(
        db, project_id, Task.priority
    )
    completed_trend = await _completed_trend(db, project_id)
    overdue_count = await _overdue_count(db, project_id)
    workload = await _workload(db, project_id)
    cf_stats = await _custom_field_stats(db, project_id)

    total_active = sum(done_breakdown.values())
    archived_row = await db.execute(
        select(func.count(Task.id)).where(
            Task.project_id == project_id, Task.archived_at.is_not(None)
        )
    )
    total_archived = int(archived_row.scalar_one())

    # Silence pyflakes — `Any` is used only via cast-helper text() above.
    _ = Any

    return ProjectStatsResponse(
        done_breakdown=done_breakdown,
        stage_breakdown=stage_breakdown,
        priority_breakdown=priority_breakdown,
        completed_trend=completed_trend,
        overdue_count=overdue_count,
        workload=workload,
        custom_field_stats=cf_stats,
        total_active=total_active,
        total_archived=total_archived,
    )


class MyStatsResponse(BaseModel):
    """Личные цифры для блока «Ваша статистика» на «Главной».

    ОБА окна приезжают одним ответом: переключатель «7 / 30 дней» на клиенте
    не должен ходить в сеть, а разница в стоимости — лишний `sum(...)` в том
    же запросе. `daily` всегда `_MY_DAYS` точек (последняя — сегодня), вид
    «7 дней» — её хвост, режется на клиенте.
    """

    completed_7: int
    completed_30: int
    created_7: int
    created_30: int
    # Состояние на сейчас, от периода НЕ зависит — фронт подписывает отдельно.
    overdue_now: int
    open_now: int
    daily: list[TrendPoint]


def _mine(employee_id: UUID):
    """Мои задачи для личной статистики — тот же набор, что на `/me/tasks`.

    «Мои» — только через `assignee_exists` (EXISTS): наивный JOIN на
    `task_assignees` размножил бы задачу по числу исполнителей и завысил цифры.

    Больше НИЧЕГО не фильтруем, и это не упущение:

    * `personal_visible_to` здесь был бы вреден. Приватность обеспечивает сам
      скоуп — считаются только задачи, где я исполнитель. А предикат выкинул
      бы мою работу в ЧУЖОМ личном пространстве: коллега вправе поручить мне
      задачу у себя, и я вправе её закрыть (`test_guest_closes_assigned_task`).
      `/me/tasks` такие задачи показывает — блок обязан их считать.
    * `Project.archived_at` тоже не трогаем. Во-первых, `/me/tasks` его не
      фильтрует, а блок — сводка того же экрана. Во-вторых, фильтр переписывал
      бы прошлое: архивация проекта задним числом стирала бы столбики из
      графика за месяцы, когда работа была сделана.

    Членство в проекте не проверяем — ровно как `/me/tasks`. (Инвариант
    «исполнитель всегда участник» на самом деле дырявый: удаление участника
    не чистит `task_assignees`. Но расходиться с `/me/tasks` в цифрах хуже.)
    """
    return and_(assignee_exists(employee_id), Task.archived_at.is_(None))


def _in_window(column, start: datetime, end: datetime, label: str):
    """`count(*) FILTER (WHERE column ∈ [start, end))`.

    `.filter()`, а не `sum(cast(..., Integer))`: CAST — ровно то, на чём
    ручка статистики уже молча ломалась апгрейдом SQLAlchemy (докстринг
    `tests/integration/test_stats_search.py`), а `count` вдобавок возвращает
    0 вместо NULL на пустой выборке. Прецедент — `app/api/projects.py`.

    Верхняя граница обязательна: без неё задача с датой из будущего (рассинхрон
    часов, ручная правка) попала бы в счётчик, но не нашла бы себе столбика в
    `daily`, и числа под графиком разошлись бы с самим графиком.
    """
    return (
        func.count()
        .filter(and_(column.is_not(None), column >= start, column < end))
        .label(label)
    )


def my_counters_stmt(employee_id: UUID, now: datetime):
    """Четыре числа по МОИМ задачам одним запросом."""
    end = start_of_tomorrow_utc(now)
    return (
        select(
            _in_window(
                Task.completed_at,
                start_of_window_utc(_MY_SHORT_DAYS, now),
                end,
                "completed_7",
            ),
            _in_window(
                Task.completed_at,
                start_of_window_utc(_MY_DAYS, now),
                end,
                "completed_30",
            ),
            func.count().filter(Task.done.is_(False)).label("open_now"),
            func.count()
            .filter(
                and_(Task.done.is_(False), Task.due_at < start_of_today_utc(now))
            )
            .label("overdue_now"),
        )
        .select_from(Task)
        .where(_mine(employee_id))
    )


def my_created_stmt(employee_id: UUID, now: datetime):
    """Заведённые МНОЙ — другая выборка, чем «мои по исполнителю».

    Отдельный запрос, а не колонка в предыдущем: задачу можно завести другому,
    и совмещать две популяции в одном WHERE значит считать не то. Именно
    поэтому руководитель, раздающий задачи, увидит здесь не ноль.
    """
    end = start_of_tomorrow_utc(now)
    return (
        select(
            _in_window(
                Task.created_at,
                start_of_window_utc(_MY_SHORT_DAYS, now),
                end,
                "created_7",
            ),
            _in_window(
                Task.created_at,
                start_of_window_utc(_MY_DAYS, now),
                end,
                "created_30",
            ),
        )
        .select_from(Task)
        .where(Task.created_by == employee_id, Task.archived_at.is_(None))
    )


def my_daily_stmt(employee_id: UUID, now: datetime):
    """Выполненные по дням за `_MY_DAYS`.

    Сутки режутся в display tz, а не в UTC: иначе день переключался бы в
    03:00 МСК и «сегодня» на графике не совпадало бы с «сегодня» в сроках
    задач (инвариант `services/taskdates.py`). Соседний `_completed_trend`
    как раз этим и болен — здесь мы его не повторяем.
    """
    # `type_=String` явно: у `timezone()` есть перегрузка с interval, и
    # нетипизированный bind полагался бы на правила разрешения перегрузок PG.
    tz = bindparam("tz", get_settings().display_timezone, type_=String)
    # Результат — timestamp БЕЗ таймзоны (наивный datetime у asyncpg): берём
    # у него `.date()` и не сравниваем с aware-значениями.
    local_day = func.date_trunc("day", func.timezone(tz, Task.completed_at))
    return (
        select(local_day.label("day"), func.count(Task.id))
        .select_from(Task)
        .where(
            _mine(employee_id),
            Task.completed_at >= start_of_window_utc(_MY_DAYS, now),
            Task.completed_at < start_of_tomorrow_utc(now),
        )
        .group_by(text("day"))
        .order_by(text("day"))
    )


async def _my_counters(
    session: AsyncSession, employee_id: UUID, now: datetime
) -> dict[str, int]:
    row = (await session.execute(my_counters_stmt(employee_id, now))).one()
    return {
        "completed_7": int(row.completed_7),
        "completed_30": int(row.completed_30),
        "open_now": int(row.open_now),
        "overdue_now": int(row.overdue_now),
    }


async def _my_created(
    session: AsyncSession, employee_id: UUID, now: datetime
) -> dict[str, int]:
    row = (await session.execute(my_created_stmt(employee_id, now))).one()
    return {"created_7": int(row.created_7), "created_30": int(row.created_30)}


async def _my_daily(
    session: AsyncSession, employee_id: UUID, now: datetime
) -> list[TrendPoint]:
    """Ряд для графика: zero-padded, ровно `_MY_DAYS` точек, последняя — сегодня."""
    rows = await session.execute(my_daily_stmt(employee_id, now))
    counts: dict[date, int] = {}
    for raw_day, count in rows.all():
        if raw_day is None:
            continue
        counts[raw_day.date()] = int(count)
    first_day = display_today(now) - timedelta(days=_MY_DAYS - 1)
    out: list[TrendPoint] = []
    for i in range(_MY_DAYS):
        d = first_day + timedelta(days=i)
        out.append(TrendPoint(day=d, count=counts.get(d, 0)))
    return out


@router.get("/me/stats", response_model=MyStatsResponse)
async def get_my_stats(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> MyStatsResponse:
    """Личная статистика для «Главной». Скоуп — сам вызывающий, не параметр.

    `require_auth_any`, как у `/me/tasks`: цифры про себя должен видеть любой
    аутентифицированный, роль в продукте тут ничего не решает.

    `now` берётся ОДИН раз на все три запроса: иначе запрос, стартовавший в
    23:59:59, посчитал бы счётчики за одни сутки, а график за другие.
    """
    now = datetime.now(UTC)
    counters = await _my_counters(db, principal.employee_id, now)
    created = await _my_created(db, principal.employee_id, now)
    daily = await _my_daily(db, principal.employee_id, now)
    return MyStatsResponse(**counters, **created, daily=daily)
