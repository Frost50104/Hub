"""Личные напоминания по задачам (0062): решения, перерасчёт, тик воркера.

ОС пользователя (24.09): «кнопку напомнить ко времени». Решения владельца:
напоминание — только себе; относительное — двигается вместе со сроком;
просрочка по-прежнему по дням (`taskdates`).

ДВА ВИДА СТРОК.
- `at` — разовое: момент выбран руками, после срабатывания строка удаляется.
- `due`/`due_day`/`start`/`start_day` + `offset_minutes` — ПРАВИЛО, которое
  живёт дальше. Сработало → `fire_at = NULL`, `fired_anchor_at` = момент
  якоря. Перенесли срок → правило взводится снова (`reschedule`); закрыли
  повторяющуюся задачу → правило переезжает на копию (`transfer_to_copies`).
  Удалять правило при срабатывании нельзя: «за 1 ч до срока» на ежедневной
  задаче пропадало бы после первого дня.

ЯКОРЯ. `due` — момент срока (у срока без времени — 09:00 его дня); `due_day` —
ВСЕГДА 09:00 дня срока: «утром в день срока» не должно превращаться в «к сроку
18:00», когда коллега допишет сроку время. То же для старта.

ВСЯ ЛОГИКА РЕШЕНИЙ — в чистых `anchor_moment`/`decide`/`may_receive`: CI гоняет
только юниты. Разбор граблей, найденных до кода (offset 0 «засыпал» бы в самом
тике, промежуточные сроки 1902/0202 при наборе года с клавиатуры, порядок
блокировок с повтором), — в плане и `docs/ARCHITECTURE.md` §«Время и
напоминания».

ПОРЯДОК БЛОКИРОВОК: правило повтора → проект → задача → напоминания. Правка
срока сначала флашит задачу, потом зовёт `reschedule` (он берёт строки
напоминаний FOR UPDATE); тик задач не блокирует вовсе (читает MVCC), поэтому
взаимной блокировки с API не бывает.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskAssignee, TaskReminder, TaskWatcher
from app.services.notify_batch import queue_many
from app.services.push_sender import send_to_employee
from app.services.taskdates import at_local, due_day
from app.services.timefmt import fmt_when

log = structlog.get_logger("task_reminders")

KIND = "task.reminder"
RELATIVE_ANCHORS = ("due", "due_day", "start", "start_day")

# База «дня»: срок без времени и якоря `*_day` напоминают в 09:00 display tz —
# в то же утро, что и пуш `task.overdue` (09:00 МСК).
REMINDER_DAY_HOUR = 9
# Якорь «прошёл», если он раньше now на столько. Покрывает выкат и смену
# лидера воркера (до ~90 с, `worker_supervisor`), но не даёт сработать на
# промежуточных сроках старых бандлов (год 1902/0202 при наборе с клавиатуры).
PASSED_GRACE = timedelta(minutes=15)
# Срок придвинули ближе, чем offset: напомним сейчас, но с запасом на
# следующую правку того же поля (человек мог ещё не закончить).
CATCHUP = timedelta(seconds=60)
# Тик срабатывает на всё, что наступает в ближайшие секунды.
FIRE_SLACK = timedelta(seconds=5)
# Разовое напоминание, опоздавшее больше чем на столько (сервис лежал),
# выбрасывается без отправки — «напоминание на 9 утра» в полдень только шум.
AT_MAX_LATE = timedelta(hours=2)
# Строка, уронившая обработку, откладывается и не держит очередь: из-за
# ORDER BY fire_at она иначе первой ломала бы каждый тик.
FAILED_ROW_BACKOFF = timedelta(minutes=5)
MAX_PER_TASK = 5
MAX_HORIZON = timedelta(days=366)
TICK_BATCH = 200
PUSH_CONCURRENCY = 2

State = Literal["armed", "fired", "no_date", "passed", "done", "archived"]
Action = Literal["fire", "arm", "sleep", "delete"]


# ─── Чистые правила ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskFacts:
    """Всё о задаче, что нужно правилам. Собирается из ORM или из строки тика."""

    due_at: datetime | None
    due_has_time: bool
    start_at: datetime | None
    start_has_time: bool
    done: bool
    archived: bool
    project_archived: bool

    @classmethod
    def of(cls, task: Task, project: Project | None) -> TaskFacts:
        return cls(
            due_at=task.due_at,
            due_has_time=task.due_has_time,
            start_at=task.start_at,
            start_has_time=task.start_has_time,
            done=task.done,
            archived=task.archived_at is not None,
            project_archived=project is not None and project.archived_at is not None,
        )


def anchor_moment(anchor: str, facts: TaskFacts) -> datetime | None:
    """Момент якоря относительного напоминания; None — даты нет."""
    if anchor in ("due", "due_day"):
        at, has_time = facts.due_at, facts.due_has_time
    elif anchor in ("start", "start_day"):
        at, has_time = facts.start_at, facts.start_has_time
    else:
        return None
    if at is None:
        return None
    if anchor in ("due", "start") and has_time:
        return at
    return at_local(due_day(at), time(REMINDER_DAY_HOUR, 0))


@dataclass(frozen=True)
class Decision:
    action: Action
    state: State
    fire_at: datetime | None = None
    # Для сработавшего правила — момент якоря, который пишется в
    # `fired_anchor_at`; для «сработало» в выдаче — от него же считается время.
    anchor_at: datetime | None = None


def _blocked(facts: TaskFacts) -> State | None:
    if facts.archived or facts.project_archived:
        return "archived"
    if facts.done:
        return "done"
    return None


def decide(
    *,
    anchor: str,
    offset_minutes: int,
    facts: TaskFacts,
    fired_anchor_at: datetime | None,
    stored_fire_at: datetime | None,
    now: datetime,
    mode: Literal["tick", "reschedule"],
) -> Decision:
    """Что делать с напоминанием сейчас.

    `tick` — воркер выбрал строку по `fire_at <= now`: отправить, перевзвести,
    уснуть или удалить. `reschedule` — даты или состояние задачи поменялись:
    пересчитать `fire_at` (разовые не трогаются).
    """
    blocked = _blocked(facts)
    if anchor == "at":
        if mode == "reschedule":
            return Decision("arm", blocked or "armed", fire_at=stored_fire_at)
        if blocked:
            return Decision("delete", blocked)
        if stored_fire_at is None or stored_fire_at < now - AT_MAX_LATE:
            return Decision("delete", "passed")
        if stored_fire_at <= now + FIRE_SLACK:
            return Decision("fire", "armed")
        return Decision("arm", "armed", fire_at=stored_fire_at)

    if blocked:
        return Decision("sleep", blocked)
    try:
        anchor_at = anchor_moment(anchor, facts)
        if anchor_at is None:
            return Decision("sleep", "no_date")
        if anchor_at < now - PASSED_GRACE:
            return Decision("sleep", "passed", anchor_at=anchor_at)
        if fired_anchor_at is not None and fired_anchor_at == anchor_at:
            return Decision("sleep", "fired", anchor_at=anchor_at)
        target = anchor_at - timedelta(minutes=offset_minutes)
    except OverflowError:
        # Год 0001 от старого клиента: арифметика вышла за datetime.
        return Decision("sleep", "passed")
    if mode == "tick":
        if target <= now + FIRE_SLACK:
            return Decision("fire", "armed", anchor_at=anchor_at)
        # Срок перенесли позже, а `reschedule` не позвали: ждём новый момент.
        return Decision("arm", "armed", fire_at=target, anchor_at=anchor_at)
    return Decision(
        "arm",
        "armed",
        fire_at=target if target > now else now + CATCHUP,
        anchor_at=anchor_at,
    )


def may_receive(
    *,
    employee_id: UUID,
    deleted: bool,
    personal_owner_id: UUID | None,
    is_member: bool,
    via_admin: bool,
    involved: bool,
) -> bool:
    """Видит ли получатель задачу — общее правило POST и тика.

    Обычный проект — участник или hub-admin (через `via_admin`: кеш роли
    пишет только staff-sync, а на staging он выключен). Личный — владелец либо
    участник-исполнитель/наблюдатель: зеркало `personal_task_scope`, hub-admin
    личное не обходит.
    """
    if deleted:
        return False
    if personal_owner_id is None:
        return is_member or via_admin
    if personal_owner_id == employee_id:
        return True
    return (is_member or via_admin) and involved


def _short(title: str, n: int = 80) -> str:
    title = title.strip().replace("\n", " ")
    return title if len(title) <= n else title[:n].rstrip() + "…"


def reminder_body(anchor: str, title: str, facts: TaskFacts, now: datetime) -> str:
    """«Сдать отчёт» — срок сегодня в 15:00 / — начало завтра / просто «…»."""
    head = f"«{_short(title)}»"
    if anchor in ("start", "start_day") and facts.start_at is not None:
        return f"{head} — начало {fmt_when(facts.start_at, facts.start_has_time, now)}"
    if facts.due_at is not None:
        return f"{head} — срок {fmt_when(facts.due_at, facts.due_has_time, now)}"
    return head


def item_state(
    *,
    anchor: str,
    offset_minutes: int,
    facts: TaskFacts,
    fired_anchor_at: datetime | None,
    fire_at: datetime | None,
    now: datetime,
) -> tuple[State, datetime | None, datetime | None]:
    """(состояние, момент срабатывания, когда сработало) — для карточки."""
    if fire_at is not None:
        blocked = _blocked(facts)
        return (blocked or "armed"), fire_at, None
    d = decide(
        anchor=anchor,
        offset_minutes=offset_minutes,
        facts=facts,
        fired_anchor_at=fired_anchor_at,
        stored_fire_at=None,
        now=now,
        mode="reschedule",
    )
    if d.state == "fired" and d.anchor_at is not None:
        return "fired", None, d.anchor_at - timedelta(minutes=offset_minutes)
    return d.state, d.fire_at if d.action == "arm" else None, None


# ─── Перерасчёт и повтор ────────────────────────────────────────────────────


async def reschedule(db: AsyncSession, task: Task, *, now: datetime | None = None) -> None:
    """Пересчитать `fire_at` относительных правил задачи. Без commit'а.

    Звать ПОСЛЕ flush'а самой задачи (порядок блокировок: задача → строки
    напоминаний). Строки берутся FOR UPDATE: если тик как раз держит правило,
    ждём его коммита и видим свежий `fired_anchor_at` — иначе только что
    сработавшее правило взвелось бы на тот же момент ещё раз.
    """
    now = now or datetime.now(UTC)
    project = await db.get(Project, task.project_id)
    facts = TaskFacts.of(task, project)
    rows = (
        await db.execute(
            select(TaskReminder.id, TaskReminder.anchor, TaskReminder.offset_minutes,
                   TaskReminder.fired_anchor_at, TaskReminder.fire_at)
            .where(TaskReminder.task_id == task.id, TaskReminder.anchor != "at")
            .with_for_update()
        )
    ).all()
    for rid, anchor, offset, fired_anchor_at, fire_at in rows:
        d = decide(
            anchor=anchor,
            offset_minutes=offset,
            facts=facts,
            fired_anchor_at=fired_anchor_at,
            stored_fire_at=fire_at,
            now=now,
            mode="reschedule",
        )
        new_fire = d.fire_at if d.action == "arm" else None
        if new_fire != fire_at:
            await db.execute(
                update(TaskReminder).where(TaskReminder.id == rid).values(fire_at=new_fire)
            )


async def transfer_to_copies(
    db: AsyncSession, moves: dict[UUID, Task], *, now: datetime | None = None
) -> None:
    """Повтор: относительные правила переезжают со старой задачи на копию.

    `moves` — старый id → копия; туда кладутся сама задача и ТОЛЬКО
    выполненные подзадачи (`set_done` подзадачи не закрывает, а клонируются
    все живые — у ещё открытой старой подзадачи правило должно остаться).
    Разовые (`at`) остаются на месте: момент выбран руками, а задача закрыта —
    тик их выбросит.
    """
    for old_id, copy in moves.items():
        moved = await db.execute(
            update(TaskReminder)
            .where(TaskReminder.task_id == old_id, TaskReminder.anchor != "at")
            .values(task_id=copy.id, fired_anchor_at=None, fire_at=None)
        )
        if moved.rowcount:
            await reschedule(db, copy, now=now)


# ─── Тик воркера ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _PushJob:
    tenant_id: UUID
    employee_id: UUID
    payload: dict[str, Any]


@dataclass(frozen=True)
class _TaskRow:
    title: str
    project_id: UUID
    personal_owner_id: UUID | None
    facts: TaskFacts


async def _load_context(
    db: AsyncSession, rows: Iterable[Any]
) -> tuple[dict[UUID, _TaskRow], set[tuple[UUID, UUID]], set[tuple[UUID, UUID]], set[UUID]]:
    """Задачи, членства, причастность и удалённые — пачкой на весь тик."""
    rows = list(rows)
    task_ids = {r.task_id for r in rows}
    emp_ids = {r.employee_id for r in rows}
    task_rows = (
        await db.execute(
            select(
                Task.id, Task.title, Task.project_id, Task.due_at, Task.due_has_time,
                Task.start_at, Task.start_has_time, Task.done, Task.archived_at,
                Project.archived_at, Project.personal_owner_id,
            )
            .join(Project, Project.id == Task.project_id)
            .where(Task.id.in_(task_ids))
        )
    ).all()
    tasks = {
        t[0]: _TaskRow(
            title=t[1],
            project_id=t[2],
            personal_owner_id=t[10],
            facts=TaskFacts(
                due_at=t[3], due_has_time=t[4], start_at=t[5], start_has_time=t[6],
                done=t[7], archived=t[8] is not None, project_archived=t[9] is not None,
            ),
        )
        for t in task_rows
    }
    project_ids = {t.project_id for t in tasks.values()}
    members = set(
        (
            await db.execute(
                select(ProjectMember.project_id, ProjectMember.employee_id).where(
                    ProjectMember.project_id.in_(project_ids),
                    ProjectMember.employee_id.in_(emp_ids),
                )
            )
        ).all()
    ) if project_ids else set()
    involved: set[tuple[UUID, UUID]] = set()
    for model in (TaskAssignee, TaskWatcher):
        involved |= set(
            (
                await db.execute(
                    select(model.task_id, model.employee_id).where(
                        model.task_id.in_(task_ids), model.employee_id.in_(emp_ids)
                    )
                )
            ).all()
        )
    deleted = set(
        (
            await db.execute(
                select(ShadowUser.employee_id).where(
                    ShadowUser.employee_id.in_(emp_ids), ShadowUser.deleted_at.is_not(None)
                )
            )
        ).scalars()
    )
    return tasks, members, involved, deleted


async def tick(now: datetime | None = None, *, tenant_id: UUID | None = None) -> dict[str, int]:
    """Один проход воркера. → счётчики для журнала.

    Свежая bypass-сессия на КАЖДЫЙ тик: `expire_on_commit=False` отдавал бы
    из identity map старые задачи. Пуши уходят фоном ПОСЛЕ commit'а и в
    своих сессиях: `send_to_employee` коммитит переданную сессию и снял бы
    блокировки тика. `tenant_id` — только для тестов на общей БД.
    """
    now = now or datetime.now(UTC)
    counts: dict[str, int] = defaultdict(int)
    jobs: list[_PushJob] = []
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        stmt = (
            select(
                TaskReminder.id, TaskReminder.tenant_id, TaskReminder.task_id,
                TaskReminder.employee_id, TaskReminder.anchor, TaskReminder.offset_minutes,
                TaskReminder.fire_at, TaskReminder.fired_anchor_at, TaskReminder.via_admin,
            )
            .where(TaskReminder.fire_at.is_not(None), TaskReminder.fire_at <= now + FIRE_SLACK)
            .order_by(TaskReminder.fire_at)
            .limit(TICK_BATCH)
            .with_for_update(skip_locked=True)
        )
        if tenant_id is not None:
            stmt = stmt.where(TaskReminder.tenant_id == tenant_id)
        rows = (await db.execute(stmt)).all()
        if not rows:
            return dict(counts)
        tasks, members, involved, deleted = await _load_context(db, rows)
        for r in rows:
            try:
                async with db.begin_nested():
                    job = await _process(db, r, tasks, members, involved, deleted, now, counts)
                if job is not None:
                    jobs.append(job)
            except Exception:  # noqa: BLE001 — одна строка не держит очередь
                log.exception("task_reminders.row_failed", reminder_id=str(r.id))
                counts["failed"] += 1
                async with db.begin_nested():
                    await db.execute(
                        update(TaskReminder)
                        .where(TaskReminder.id == r.id)
                        .values(fire_at=now + FAILED_ROW_BACKOFF)
                    )
        await db.commit()
    if jobs:
        _schedule_pushes(jobs)
    log.info("task_reminders.tick", **counts)
    return dict(counts)


async def _process(
    db: AsyncSession,
    r: Any,
    tasks: dict[UUID, _TaskRow],
    members: set[tuple[UUID, UUID]],
    involved: set[tuple[UUID, UUID]],
    deleted: set[UUID],
    now: datetime,
    counts: dict[str, int],
) -> _PushJob | None:
    task = tasks.get(r.task_id)
    if task is None:
        # Задачи нет (удалили в ту же секунду) или она невидима (шаблон).
        await db.execute(delete(TaskReminder).where(TaskReminder.id == r.id))
        counts["dropped"] += 1
        return None
    visible = may_receive(
        employee_id=r.employee_id,
        deleted=r.employee_id in deleted,
        personal_owner_id=task.personal_owner_id,
        is_member=(task.project_id, r.employee_id) in members,
        via_admin=r.via_admin,
        involved=(r.task_id, r.employee_id) in involved,
    )
    if not visible:
        await db.execute(delete(TaskReminder).where(TaskReminder.id == r.id))
        counts["no_access"] += 1
        return None
    d = decide(
        anchor=r.anchor,
        offset_minutes=r.offset_minutes,
        facts=task.facts,
        fired_anchor_at=r.fired_anchor_at,
        stored_fire_at=r.fire_at,
        now=now,
        mode="tick",
    )
    if d.action == "delete":
        await db.execute(delete(TaskReminder).where(TaskReminder.id == r.id))
        counts["dropped"] += 1
        return None
    if d.action in ("sleep", "arm"):
        new_fire = d.fire_at if d.action == "arm" else None
        await db.execute(
            update(TaskReminder).where(TaskReminder.id == r.id).values(fire_at=new_fire)
        )
        counts["slept" if d.action == "sleep" else "rearmed"] += 1
        return None

    # Отправка: разовое удаляется, правило засыпает до следующего якоря.
    if r.anchor == "at":
        await db.execute(delete(TaskReminder).where(TaskReminder.id == r.id))
    else:
        await db.execute(
            update(TaskReminder)
            .where(TaskReminder.id == r.id)
            .values(fire_at=None, fired_anchor_at=d.anchor_at)
        )
    body = reminder_body(r.anchor, task.title, task.facts, now)
    _n, batch = await queue_many(
        db,
        tenant_id=r.tenant_id,
        employee_ids=[r.employee_id],
        kind=KIND,
        title="Напоминание",
        body=body,
        url=f"/projects/{task.project_id}?task={r.task_id}",
        payload={
            "task_id": str(r.task_id),
            "anchor": r.anchor,
            "offset_minutes": r.offset_minutes,
        },
    )
    counts["fired"] += 1
    if batch is None:
        return None
    return _PushJob(tenant_id=r.tenant_id, employee_id=r.employee_id, payload=batch.payload)


_push_sem: asyncio.Semaphore | None = None
_pending: set[asyncio.Task] = set()


def _semaphore() -> asyncio.Semaphore:
    global _push_sem
    if _push_sem is None:
        _push_sem = asyncio.Semaphore(PUSH_CONCURRENCY)
    return _push_sem


def _schedule_pushes(jobs: list[_PushJob]) -> None:
    """Пуши фоном, группами по тенанту: `push_subscriptions` под FORCE RLS,
    сессия группы — своя. Общий семафор держит пул соединений API живым."""
    by_tenant: dict[UUID, list[_PushJob]] = defaultdict(list)
    for job in jobs:
        by_tenant[job.tenant_id].append(job)
    for tid, items in by_tenant.items():
        task = asyncio.create_task(_send_group(tid, items))
        _pending.add(task)
        task.add_done_callback(_pending.discard)


async def _send_group(tenant_id: UUID, items: list[_PushJob]) -> None:
    async with _semaphore():
        try:
            async with tenant_scoped_session(tenant_id) as session:
                for item in items:
                    try:
                        await send_to_employee(
                            session, employee_id=item.employee_id, payload=item.payload
                        )
                    except Exception as e:  # noqa: BLE001 — не роняем группу
                        log.warning(
                            "task_reminders.push_failed",
                            employee_id=str(item.employee_id),
                            err=str(e),
                        )
        except Exception as e:  # noqa: BLE001
            log.warning("task_reminders.push_session_failed", err=str(e))


async def start_worker() -> None:
    """Вечный цикл под `supervise` + лидер-лок. Исключения ловит САМ: бэкофф
    супервизора не сбрасывается (`worker_supervisor.py`), и одна ошибка БД
    иначе копила бы паузу до 300 с на всё время жизни процесса."""
    settings = get_settings()
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 — воркер не должен умирать от одного сбоя
            log.exception("task_reminders.tick_failed")
        await asyncio.sleep(settings.task_reminders_poll_sec)
