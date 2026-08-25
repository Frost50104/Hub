"""Колонки доски (0044): свободные имена, независимость от «выполнена».

Колонка — это только имя и позиция. Состояние задачи (`done`) живёт отдельно:
перенос между колонками его не трогает, галочка не двигает карточку. Проекту
нужна хотя бы одна колонка — иначе задаче негде лежать.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.stages import create_stage, delete_stage, list_project_stages, update_stage
from app.api.tasks import create_task, get_task, update_task
from app.schemas.project import ProjectCreate
from app.schemas.stage import StageCreate, StageUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _by_name(db: AsyncSession, project_id: uuid.UUID, owner):
    stages = await list_project_stages(project_id, principal=owner, db=db)
    return {s.name: s for s in stages}


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Stages {slug}"), owner, db)
    return owner, project


async def test_new_project_gets_four_default_stages(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st1")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.name for s in stages] == ["К выполнению", "В работе", "На проверке", "Готово"]
    assert [s.position for s in stages] == [0, 1, 2, 3]
    assert all(s.task_count == 0 for s in stages)


async def test_task_without_stage_lands_in_first_column(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "st2")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(project.id, TaskCreate(title="Без колонки"), owner, db)
    assert task.stage_id == stages[0].id
    assert task.done is False and task.completed_at is None

    explicit = await create_task(
        project.id, TaskCreate(title="В третью", stage_id=stages[2].id), owner, db
    )
    assert explicit.stage_id == stages[2].id
    # Колонка «Готово» больше ничего не означает: задача в ней не выполнена.
    finish = await create_task(
        project.id, TaskCreate(title="В Готово", stage_id=stages[3].id), owner, db
    )
    assert finish.done is False and finish.completed_at is None


async def test_done_and_column_are_independent(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st3")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(project.id, TaskCreate(title="Две оси"), owner, db)

    # Галочка не двигает карточку.
    done = await update_task(task.id, TaskUpdate(done=True), owner, db)
    assert done.done is True and done.completed_at is not None
    assert done.stage_id == stages[0].id

    # Перенос не меняет состояние.
    moved = await update_task(task.id, TaskUpdate(stage_id=stages[2].id), owner, db)
    assert moved.stage_id == stages[2].id
    assert moved.done is True and moved.completed_at is not None

    # Снятие галочки чистит дату закрытия.
    back = await update_task(task.id, TaskUpdate(done=False), owner, db)
    assert back.done is False and back.completed_at is None
    assert back.stage_id == stages[2].id


async def test_legacy_status_query_is_rejected_not_ignored(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Старый бандл должен получить ошибку, а не НЕотфильтрованный список.

    Тело с legacy-полем отбивает `extra="forbid"` на схемах (0045, юнит-тесты
    в `tests/unit/test_legacy_payloads.py`), а вот неизвестный query-параметр
    FastAPI игнорирует МОЛЧА: старый бандл получил бы 200 и все задачи там,
    где просил только «в работе». Здесь — две ручки, которых не касается
    регресс `list_tasks` в `test_feedback_2026_08.py`.
    """
    from app.api.calendar import list_calendar_tasks
    from app.api.me_tasks import list_my_tasks

    owner, project = await _seed(db, tenant_id, "st4")
    await create_task(project.id, TaskCreate(title="Обычная"), owner, db)

    with pytest.raises(HTTPException) as exc:
        await list_my_tasks(
            done=None,
            status_="in_progress",
            due_window=None,
            include_archived=False,
            include_personal=False,
            principal=owner,
            db=db,
        )
    assert exc.value.status_code == 422
    assert "обновите страницу" in exc.value.detail.lower()

    with pytest.raises(HTTPException) as exc:
        await list_calendar_tasks(
            project.id,
            from_="2026-08-01",
            to="2026-08-31",
            done=None,
            status_="done",
            assignee_id=None,
            priority=None,
            principal=owner,
            db=db,
        )
    assert exc.value.status_code == 422

    # Без legacy-параметра те же ручки работают.
    assert len(
        await list_calendar_tasks(
            project.id,
            from_="2026-08-01",
            to="2026-08-31",
            done=None,
            status_=None,
            assignee_id=None,
            priority=None,
            principal=owner,
            db=db,
        )
    ) == 0


async def test_custom_columns_live_freely(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st5")
    idea = await create_stage(project.id, StageCreate(name="Идея", position=0), owner, db)
    stages = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.name for s in stages][0] == "Идея"
    assert [s.position for s in stages] == [0, 1, 2, 3, 4]

    task = await create_task(project.id, TaskCreate(title="Задача", stage_id=idea.id), owner, db)
    renamed = await update_stage(idea.id, StageUpdate(name="Согласование"), owner, db)
    assert renamed.name == "Согласование"
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id == idea.id and fresh.done is False


async def test_delete_column_moves_tasks_and_keeps_state(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _seed(db, tenant_id, "st6")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(
        project.id, TaskCreate(title="Выполненная", stage_id=stages[3].id), owner, db
    )
    await update_task(task.id, TaskUpdate(done=True), owner, db)

    with pytest.raises(HTTPException) as exc:
        await delete_stage(stages[3].id, move_to=None, principal=owner, db=db)
    assert exc.value.status_code == 409, "с задачами нужен move_to"

    await delete_stage(stages[3].id, move_to=stages[0].id, principal=owner, db=db)
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id == stages[0].id
    # Перенос при удалении колонки — не «вернуть в работу».
    assert fresh.done is True and fresh.completed_at is not None
    left = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.position for s in left] == [0, 1, 2]


async def test_last_column_cannot_be_deleted(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "st7")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    for s in stages[1:]:
        await delete_stage(s.id, move_to=stages[0].id, principal=owner, db=db)
    left = await list_project_stages(project.id, principal=owner, db=db)
    assert len(left) == 1
    with pytest.raises(HTTPException) as exc:
        await delete_stage(left[0].id, move_to=None, principal=owner, db=db)
    assert exc.value.status_code == 409
    assert "единственная колонка" in exc.value.detail.lower()
    # И задача в проекте с одной колонкой по-прежнему создаётся.
    task = await create_task(project.id, TaskCreate(title="Одна колонка"), owner, db)
    assert task.stage_id == left[0].id


async def test_stats_counts_by_column_and_state(db: AsyncSession, tenant_id: uuid.UUID):
    from app.api.stats import get_stats

    owner, project = await _seed(db, tenant_id, "st8")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    await create_task(project.id, TaskCreate(title="A"), owner, db)
    b = await create_task(
        project.id, TaskCreate(title="B", stage_id=stages[3].id), owner, db
    )
    await update_task(b.id, TaskUpdate(done=True), owner, db)

    stats = await get_stats(project.id, principal=owner, db=db)
    assert stats.stage_breakdown[str(stages[0].id)] == 1
    assert stats.stage_breakdown[str(stages[3].id)] == 1
    assert stats.done_breakdown == {"done": 1, "open": 1}
    assert stats.total_active == 2


async def test_moving_column_is_quiet_but_completing_notifies(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Пуш — только за «выполнена»; перенос карточки людей не будит."""
    from sqlalchemy import select

    from app.models.notification import Notification
    from app.models.task import TaskWatcher

    owner, project = await _seed(db, tenant_id, "st9")
    watcher = make_principal(
        tenant_id, email="watcher-st9@t.ru", role="member", tenant_slug="st9"
    )
    await _register(db, watcher, org_role="office")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(project.id, TaskCreate(title="Наблюдаемая"), owner, db)
    db.add(
        TaskWatcher(
            task_id=task.id,
            employee_id=watcher.employee_id,
            tenant_id=tenant_id,
            added_reason="manual",
        )
    )
    await db.flush()

    async def _inbox() -> list[str]:
        rows = await db.execute(
            select(Notification.title).where(
                Notification.employee_id == watcher.employee_id
            )
        )
        return list(rows.scalars().all())

    await update_task(task.id, TaskUpdate(stage_id=stages[2].id), owner, db)
    assert await _inbox() == [], "перенос между колонками — не событие для пуша"

    await update_task(task.id, TaskUpdate(done=True), owner, db)
    assert await _inbox() == ["Задача выполнена"]

    await update_task(task.id, TaskUpdate(done=False), owner, db)
    assert await _inbox() == ["Задача выполнена", "Задача вернулась в работу"]


async def test_db_guards_done_and_completed_at(db: AsyncSession, tenant_id: uuid.UUID):
    """CHECK-констрейнт, а не только код: рассогласование невозможно."""
    from sqlalchemy.exc import IntegrityError

    from app.models.task import Task

    owner, project = await _seed(db, tenant_id, "st10")
    task = await create_task(project.id, TaskCreate(title="Хитрая"), owner, db)
    row = await db.get(Task, task.id)
    row.done = True  # без completed_at — ровно то, что ловит CHECK
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_legacy_columns_are_gone(db: AsyncSession):
    """0045 унесла колонки старой модели — и ничего лишнего.

    Проверяем СХЕМУ, а не поведение: колонки уже никто не читал, поэтому
    забытый `DROP COLUMN` не уронил бы ни один другой тест (схема в тестах
    поднимается прогоном миграций, дрейф модель↔БД никто не сверяет).
    """
    from sqlalchemy import text

    rows = await db.execute(
        text(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            "WHERE (table_name = 'tasks' AND column_name = 'status') "
            "   OR (table_name = 'project_stages' AND column_name = 'system_status')"
        )
    )
    assert rows.scalars().all() == []

    # Заодно: индексы-замены на месте, а зависевшие от колонки ушли вместе с ней.
    names = set(
        (
            await db.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'tasks'")
            )
        )
        .scalars()
        .all()
    )
    assert "ix_tasks_project_stage_position" in names
    assert "ix_tasks_due_at_open" in names
    assert "ix_tasks_project_status_position" not in names
    assert "ix_tasks_due_at_active" not in names


async def test_partial_index_matches_the_open_predicate(db: AsyncSession):
    """У «невыполненных со сроком» обязан быть свой частичный индекс.

    Старый `ix_tasks_due_at_active` частичный по `status <> 'done'`: с переходом
    на `done` запросы просрочки и обе джобы вышли бы из-под него МОЛЧА — без
    ошибки и без единого падающего теста, — а 0045 унесла бы индекс вместе с
    колонкой. Сверяем определение, а не план: на пустой таблице планировщик
    выбирает любой индекс и тест был бы фиктивным.
    """
    from sqlalchemy import text

    definition = (
        await db.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'tasks' AND indexname = 'ix_tasks_due_at_open'"
            )
        )
    ).scalar_one_or_none()
    assert definition is not None, "индекс-близнец по done не создан миграцией 0044"
    assert "NOT done" in definition and "archived_at IS NULL" in definition
    assert "(tenant_id, due_at)" in definition.replace('"', "")
