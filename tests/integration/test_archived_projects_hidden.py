"""Архив = запарковано: задачи архивного проекта уходят из ЛИЧНЫХ списков и
перестают звонить (31.08).

ОС владельца: он видел в `/my` → «Предстоит» задачи проекта, который сам убрал
в архив (13 штук со сроками в декабре). `GET /me/tasks` фильтровал только
`Task.archived_at`, а `Project.archived_at` не смотрел — в отличие от поиска.
Тот же корень был у cron-джоб: 30 ноября они разослали бы пуши «срок завтра» по
запаркованному проекту.

Здесь закреплены ОБЕ половины правила, потому что каждая по отдельности
выглядит как недоделка:

* дедлайнные напоминания (`due_soon`, `overdue`) архив гасит;
* `/me/stats` считает архивные проекты в истории (`completed_*`) и НЕ считает в
  состоянии на сейчас (`open_now`, `overdue_now`);
* `t_search_tasks` архивный проект прячет в кросс-проектном поиске и ПОКАЗЫВАЕТ,
  когда человек назвал его сам.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.me_tasks import list_my_tasks
from app.api.projects import archive_project, create_project
from app.api.stats import get_my_stats
from app.api.tasks import create_task, update_task
from app.jobs import due_soon, overdue
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.assistant.context import ToolContext
from app.services.assistant.tools import (
    MyTasksArgs,
    SearchTasksArgs,
    t_my_tasks,
    t_search_tasks,
)
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
SOON = NOW + timedelta(hours=12)  # окно due_soon: [now, now + 24h)
LONG_AGO = NOW - timedelta(days=3)  # день срока раньше сегодняшнего


class _Seed:
    """Владелец, живой проект и его архивный сосед — с одинаковым набором задач.

    Одинаковый набор нужен, чтобы каждый ассерт был ПАРНЫМ: «архивной нет» без
    «живая есть» одинаково хорошо проходит и на правильном фильтре, и на
    сломанном запросе, который не возвращает ничего.
    """

    def __init__(self, owner, alive, dead, tasks: dict[str, uuid.UUID]) -> None:
        self.owner = owner
        self.alive = alive
        self.dead = dead
        self.tasks = tasks

    def id(self, name: str) -> uuid.UUID:
        return self.tasks[name]


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str) -> _Seed:
    owner = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    alive = await create_project(ProjectCreate(name=f"Живой {slug}"), owner, db)
    dead = await create_project(ProjectCreate(name=f"Архивный {slug}"), owner, db)

    tasks: dict[str, uuid.UUID] = {}
    for tag, project in (("alive", alive), ("dead", dead)):
        for name, due in (("soon", SOON), ("late", LONG_AGO)):
            created = await create_task(
                project.id,
                TaskCreate(
                    title=f"{name} {tag} {slug}",
                    due_at=due,
                    assignee_ids=[owner.employee_id],
                ),
                owner,
                db,
            )
            tasks[f"{name}_{tag}"] = created.id
        # Выполненная — ради `completed_*`: она обязана считаться и после
        # архивации проекта.
        done = await create_task(
            project.id,
            TaskCreate(title=f"done {tag} {slug}", assignee_ids=[owner.employee_id]),
            owner,
            db,
        )
        await update_task(done.id, TaskUpdate(done=True), owner, db)
        tasks[f"done_{tag}"] = done.id

    await db.commit()
    # Архивируем ПОСЛЕ того, как всё заведено: так и бывает в жизни, и заодно
    # обходится гейт `assert_project_accepts_tasks`.
    await archive_project(dead.id, owner, db)
    return _Seed(owner, alive, dead, tasks)


async def _my(seed: _Seed, db: AsyncSession, **kw) -> list[uuid.UUID]:
    rows = await list_my_tasks(
        done=kw.pop("done", None),
        status_=None,
        due_window=kw.pop("due_window", None),
        include_archived=kw.pop("include_archived", False),
        include_personal=False,
        principal=seed.owner,
        db=db,
    )
    return [t.id for t in rows]


# ─── /me/tasks ──────────────────────────────────────────────────────────────


async def test_my_tasks_hides_archived_project_and_keeps_the_neighbour(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, "ah1")
    ids = await _my(seed, db)

    assert seed.id("soon_alive") in ids
    assert seed.id("late_alive") in ids
    assert seed.id("soon_dead") not in ids, "задача архивного проекта в «Моих задачах»"
    assert seed.id("late_dead") not in ids


async def test_my_tasks_windows_are_filtered_too(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Окна — отдельные ветки `where`, и фильтр обязан стоять до них.

    Именно окно «Предстоит» и показало проблему владельцу.
    """
    seed = await _seed(db, tenant_id, "ah2")

    upcoming = await _my(seed, db, due_window="upcoming")
    assert seed.id("soon_alive") in upcoming
    assert seed.id("soon_dead") not in upcoming

    late = await _my(seed, db, due_window="overdue")
    assert seed.id("late_alive") in late
    assert seed.id("late_dead") not in late


async def test_include_archived_returns_them_back(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Флаг один на оба архива — «покажи убранное». Клиент его не шлёт, но
    ручка обязана уметь: иначе задачи станут недостижимы через API вовсе."""
    seed = await _seed(db, tenant_id, "ah3")
    ids = await _my(seed, db, include_archived=True)

    assert seed.id("soon_dead") in ids
    assert seed.id("soon_alive") in ids


# ─── /me/stats: история считается, состояние на сейчас — нет ────────────────


async def test_stats_counts_archive_in_history_but_not_in_now(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Половинчатость — РЕШЕНИЕ, а не забытый случай.

    `open_now`/`overdue_now` стоят на одном экране со списком, из которого
    архивные ушли, — разойтись с ним они не вправе. `completed_*` и график —
    история: фильтр там стирал бы столбики за месяцы, когда работа была
    сделана. Без этого теста «недофильтрованное» состояние выглядит багом и
    его дочинят.
    """
    seed = await _seed(db, tenant_id, "ah4")
    stats = await get_my_stats(seed.owner, db)

    # Заведено по 2 открытых и 1 просроченной на проект; видно только живой.
    assert stats.open_now == 2
    assert stats.overdue_now == 1
    # А выполненные считаются ОБА — и в архивном проекте тоже.
    assert stats.completed_30 == 2
    assert sum(p.count for p in stats.daily) == 2


# ─── Дедлайнные напоминания ────────────────────────────────────────────────


async def test_due_soon_job_skips_archived_project(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, "ah5")
    ids = [t.id for t in (await db.execute(due_soon.scan_stmt(NOW))).scalars()]

    assert seed.id("soon_alive") in ids
    assert seed.id("soon_dead") not in ids, "пуш «срок завтра» по запаркованному"


async def test_overdue_job_skips_archived_project(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, "ah6")
    ids = [t.id for t in (await db.execute(overdue.scan_stmt(NOW))).scalars()]

    assert seed.id("late_alive") in ids
    assert seed.id("late_dead") not in ids


# ─── Ассистент ─────────────────────────────────────────────────────────────


def _ctx(db: AsyncSession, principal) -> ToolContext:
    return ToolContext(db=db, principal=principal, profile=None)


async def test_assistant_my_tasks_mirrors_the_screen(
    db: AsyncSession, tenant_id: uuid.UUID
):
    seed = await _seed(db, tenant_id, "ah7")
    titles = [t["title"] for t in (await t_my_tasks(_ctx(db, seed.owner), MyTasksArgs()))["tasks"]]

    assert "soon alive ah7" in titles
    assert "soon dead ah7" not in titles


async def test_assistant_search_hides_archive_but_not_when_asked_by_name(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Безусловный фильтр соврал бы: «в проекте X задач нет» — при том, что
    страница проекта их показывает, а правка там разрешена."""
    seed = await _seed(db, tenant_id, "ah8")
    ctx = _ctx(db, seed.owner)

    wide = [t["title"] for t in (await t_search_tasks(ctx, SearchTasksArgs()))["tasks"]]
    assert "soon alive ah8" in wide
    assert "soon dead ah8" not in wide

    named = await t_search_tasks(ctx, SearchTasksArgs(project=seed.dead.name))
    assert "soon dead ah8" in [t["title"] for t in named["tasks"]]
