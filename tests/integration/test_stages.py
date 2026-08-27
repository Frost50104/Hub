"""Колонки доски (0044): свободные имена, независимость от «выполнена».

Колонка — это только имя и позиция. Состояние задачи (`done`) живёт отдельно:
перенос между колонками его не трогает, галочка не двигает карточку. Колонок у
проекта может не быть вовсе (26.08): новый проект рождается пустым, задача в
нём заводится без колонки, а удалить можно любую колонку, включая последнюю.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.me_tasks import list_my_tasks
from app.api.projects import create_project
from app.api.stages import create_stage, delete_stage, list_project_stages, update_stage
from app.api.stats import get_stats
from app.api.tasks import create_task, get_task, list_tasks, update_task
from app.schemas.project import ProjectCreate
from app.schemas.stage import StageCreate, StageUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal, seed_stages
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
    # Колонки — явным сидом: новый проект их не создаёт, а тестам ниже нужна
    # именно доска, а не пустой проект.
    await seed_stages(db, project.id, owner)
    return owner, project


async def test_new_project_has_no_stages(db: AsyncSession, tenant_id: uuid.UUID):
    """Новый проект рождается БЕЗ колонок — их создаёт человек, когда захочет.

    До 26.08 здесь была четвёрка «К выполнению / В работе / На проверке /
    Готово»: раскладка, которую никто не выбирал, но которая занимала доску.
    """
    owner = make_principal(
        tenant_id, email="owner-st1@t.ru", role="member", tenant_slug="st1"
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name="Stages st1"), owner, db)
    assert await list_project_stages(project.id, principal=owner, db=db) == []


async def test_task_in_project_without_columns_has_none(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Проект без колонок задачи принимает: они просто без колонки (0046).

    Регресс-тест на 409 «В проекте нет ни одной колонки»: он опирался на снятый
    инвариант и ронял бы создание задачи в КАЖДОМ новом проекте.
    """
    owner = make_principal(
        tenant_id, email="owner-st1b@t.ru", role="member", tenant_slug="st1b"
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name="Stages st1b"), owner, db)
    task = await create_task(project.id, TaskCreate(title="Без доски"), owner, db)
    assert task.stage_id is None
    # И она видна в списке проекта — доска не единственный экран.
    rows = await list_tasks(
        project.id,
        include_archived=False,
        done=None,
        status_=None,
        assignee_id=None,
        priority=None,
        label=None,
        due_from=None,
        due_to=None,
        sort="position",
        order="asc",
        principal=owner,
        db=db,
        stage_id=None,
    )
    assert [t.id for t in rows] == [task.id]


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
        await delete_stage(stages[3].id, move_to=None, detach=False, principal=owner, db=db)
    assert exc.value.status_code == 409, "с задачами нужен move_to"

    await delete_stage(stages[3].id, move_to=stages[0].id, detach=False, principal=owner, db=db)
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id == stages[0].id
    # Перенос при удалении колонки — не «вернуть в работу».
    assert fresh.done is True and fresh.completed_at is not None
    left = await list_project_stages(project.id, principal=owner, db=db)
    assert [s.position for s in left] == [0, 1, 2]


async def test_last_column_can_be_deleted(db: AsyncSession, tenant_id: uuid.UUID):
    """Из проекта с одной колонкой можно вернуться к пустой доске.

    Раньше здесь стоял 409 «единственная колонка»: он охранял инвариант «≥1
    колонка», который сам же и делал ловушкой — создав первую колонку по
    ошибке, выйти было нельзя.
    """
    owner, project = await _seed(db, tenant_id, "st7")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    for s in stages[1:]:
        await delete_stage(s.id, move_to=stages[0].id, detach=False, principal=owner, db=db)
    left = await list_project_stages(project.id, principal=owner, db=db)
    assert len(left) == 1

    await delete_stage(left[0].id, move_to=None, detach=False, principal=owner, db=db)
    assert await list_project_stages(project.id, principal=owner, db=db) == []
    # И задача в проекте без колонок по-прежнему создаётся — просто без колонки.
    task = await create_task(project.id, TaskCreate(title="Пустая доска"), owner, db)
    assert task.stage_id is None


async def test_delete_with_tasks_needs_move_to_or_detach(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Судьбу задач выбирает человек: молча снять колонку у пачки нельзя."""
    owner, project = await _seed(db, tenant_id, "st7b")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(
        project.id, TaskCreate(title="Живая", stage_id=stages[0].id), owner, db
    )
    with pytest.raises(HTTPException) as exc:
        await delete_stage(stages[0].id, move_to=None, detach=False, principal=owner, db=db)
    assert exc.value.status_code == 409

    await delete_stage(stages[0].id, move_to=None, detach=True, principal=owner, db=db)
    fresh = await get_task(task.id, owner, db)
    assert fresh.stage_id is None
    # Задача цела и осталась в проекте — «без колонки», а не удалена.
    assert fresh.title == "Живая" and fresh.done is False


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


# ─── Задача без статуса (0046) ───────────────────────────────────────────────


async def test_explicit_null_clears_the_status(db: AsyncSession, tenant_id: uuid.UUID):
    """Прочерк в поле «Статус» снимает колонку, а не отвечает 422.

    До 0046 у задачи колонка была обязательна, и явный `null` отвергался.
    Требование изменилось: доска показывает только задачи со статусом, а
    остальные живут в списке.
    """
    owner, project = await _seed(db, tenant_id, "st11")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    task = await create_task(project.id, TaskCreate(title="Хвост из архива"), owner, db)
    assert task.stage_id == stages[0].id

    cleared = await update_task(task.id, TaskUpdate(stage_id=None), owner, db)
    assert cleared.stage_id is None
    # Состояние задачи — независимая ось: снятие статуса её не трогает.
    assert cleared.done is False

    back = await update_task(task.id, TaskUpdate(stage_id=stages[1].id), owner, db)
    assert back.stage_id == stages[1].id


async def test_task_without_status_stays_in_lists(db: AsyncSession, tenant_id: uuid.UUID):
    """Снятый статус убирает задачу с ДОСКИ, а не из продукта.

    Самое опасное место — `/me/tasks`: там INNER JOIN на `project_stages`
    выкинул бы такую задачу вместе с назначением, то есть с главного экрана
    исполнителя.
    """
    owner, project = await _seed(db, tenant_id, "st12")
    task = await create_task(
        project.id,
        TaskCreate(title="Без статуса", assignee_ids=[owner.employee_id]),
        owner,
        db,
    )
    await update_task(task.id, TaskUpdate(stage_id=None), owner, db)

    rows = await list_tasks(
        project.id,
        include_archived=False,
        done=None,
        status_=None,
        assignee_id=None,
        priority=None,
        label=None,
        due_from=None,
        due_to=None,
        sort="position",
        order="asc",
        principal=owner,
        db=db,
        stage_id=None,
    )
    assert [t.id for t in rows] == [task.id]
    assert rows[0].stage_id is None

    mine = await list_my_tasks(
        done=None, status_=None, due_window=None, include_archived=False,
        include_personal=False, principal=owner, db=db,
    )
    assert task.id in [t.id for t in mine]
    assert next(t for t in mine if t.id == task.id).stage_name is None


async def test_stats_counts_tasks_without_status(db: AsyncSession, tenant_id: uuid.UUID):
    """Срез дашборда не должен терять задачи без статуса.

    `group_by(stage_id)` отдаёт их ключом «None» — фронт рисует по нему
    отдельный сегмент, иначе пончик молча недосчитывает.
    """
    owner, project = await _seed(db, tenant_id, "st13")
    stages = await list_project_stages(project.id, principal=owner, db=db)
    kept = await create_task(project.id, TaskCreate(title="В колонке"), owner, db)
    dropped = await create_task(project.id, TaskCreate(title="Без статуса"), owner, db)
    await update_task(dropped.id, TaskUpdate(stage_id=None), owner, db)

    stats = await get_stats(project.id, principal=owner, db=db)
    assert stats.stage_breakdown[str(stages[0].id)] == 1
    assert stats.stage_breakdown["None"] == 1
    assert sum(stats.stage_breakdown.values()) == 2
    assert kept.stage_id is not None


async def test_assignee_viewer_may_clear_the_status(db: AsyncSession, tenant_id: uuid.UUID):
    """Исполнитель двигает СВОЮ задачу по колонкам даже с ролью viewer — значит
    и убирает её с доски. Это следствие `ASSIGNEE_EDITABLE_FIELDS`, а не
    случайность: фиксируем, чтобы правка гейта не сняла право молча."""
    owner, project = await _seed(db, tenant_id, "st14")
    worker = make_principal(
        tenant_id, email="worker-st14@t.ru", role="member", tenant_slug="st14"
    )
    await _register(db, worker)
    task = await create_task(
        project.id,
        TaskCreate(title="Моя задача", assignee_ids=[worker.employee_id]),
        owner,
        db,
    )
    cleared = await update_task(task.id, TaskUpdate(stage_id=None), worker, db)
    assert cleared.stage_id is None
