"""Множественные исполнители задач (0034).

Держит четыре группы инвариантов:
1. Контракт ответа: `assignees` — источник истины, легаси-поля выводятся из него.
2. Отсутствие фан-аута: списочные ручки не должны дублировать задачу по числу
   исполнителей (первопричина «дублей карточек на доске»).
3. Побочные эффекты: watcher + авто-viewer на каждого добавленного; снятие их
   НЕ снимает.
4. Обратная совместимость со старыми PWA-бандлами, которые шлют `assignee_id`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar import list_calendar_tasks
from app.api.me_tasks import list_my_tasks
from app.api.projects import create_project
from app.api.stats import get_stats
from app.api.tasks import (
    add_task_assignee,
    create_task,
    get_task,
    list_tasks,
    remove_task_assignee,
    update_task,
)
from app.models.project import ProjectMember
from app.models.task import TaskActivity, TaskAssignee, TaskWatcher
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskAssigneeAdd, TaskCreate, TaskUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str, people: int = 2):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Мульти {slug}"), owner, db)
    others = []
    for i in range(people):
        p = make_principal(
            tenant_id,
            email=f"user{i}-{slug}@t.ru",
            full_name=f"Юзер {i} {slug}",
            role="member",
            tenant_slug=slug,
        )
        await _register(db, p)
        others.append(p)
    return owner, project, others


async def _list(db, project_id, principal, *, assignee_id=None):
    """list_tasks с явными Query-дефолтами (напрямую FastAPI их не резолвит)."""
    return await list_tasks(
        project_id,
        include_archived=False,
        status_=None,
        assignee_id=assignee_id,
        section_id=None,
        priority=None,
        label=None,
        due_from=None,
        due_to=None,
        sort="position",
        order="asc",
        principal=principal,
        db=db,
    )


async def _assignee_rows(db: AsyncSession, task_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        select(TaskAssignee.employee_id)
        .where(TaskAssignee.task_id == task_id)
        .order_by(TaskAssignee.position)
    )
    return list(rows.scalars().all())


# ─── Контракт ответа ────────────────────────────────────────────────────────


async def test_create_with_multiple_assignees_returns_all_ordered(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "ma1")
    task = await create_task(
        project.id,
        TaskCreate(title="Втроём", assignee_ids=[b.employee_id, a.employee_id]),
        owner,
        db,
    )
    assert [x.employee_id for x in task.assignees] == [b.employee_id, a.employee_id]
    assert await _assignee_rows(db, task.id) == [b.employee_id, a.employee_id]


async def test_legacy_fields_mirror_first_assignee(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "ma2")
    task = await create_task(
        project.id,
        TaskCreate(title="Зеркало", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    assert task.assignee_id == a.employee_id
    assert task.assignee is not None
    assert task.assignee.employee_id == a.employee_id


async def test_patch_replaces_whole_set(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, (a, b) = await _seed(db, tenant_id, "ma3")
    task = await create_task(
        project.id, TaskCreate(title="Замена", assignee_ids=[a.employee_id]), owner, db
    )
    updated = await update_task(
        task.id,
        TaskUpdate.model_validate({"assignee_ids": [str(b.employee_id)]}),
        owner,
        db,
    )
    assert [x.employee_id for x in updated.assignees] == [b.employee_id]
    assert await _assignee_rows(db, task.id) == [b.employee_id]


async def test_max_assignees_enforced(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, people = await _seed(db, tenant_id, "ma4", people=11)
    with pytest.raises(Exception) as exc:
        await create_task(
            project.id,
            TaskCreate.model_validate(
                {
                    "title": "Слишком много",
                    "assignee_ids": [str(p.employee_id) for p in people],
                }
            ),
            owner,
            db,
        )
    assert exc.value is not None


async def test_unknown_employee_404_and_no_partial_rows(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """404 на одном из списка не должен оставить остальных записанными."""
    owner, project, (a, _b) = await _seed(db, tenant_id, "ma5")
    task = await create_task(project.id, TaskCreate(title="Частично"), owner, db)
    with pytest.raises(Exception) as exc:
        await update_task(
            task.id,
            TaskUpdate.model_validate(
                {"assignee_ids": [str(a.employee_id), str(uuid.uuid4())]}
            ),
            owner,
            db,
        )
    assert getattr(exc.value, "status_code", None) == 404
    await db.rollback()
    assert await _assignee_rows(db, task.id) == []


# ─── Побочные эффекты ───────────────────────────────────────────────────────


async def test_patch_adds_watcher_and_membership_for_each_added(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "ma6")
    task = await create_task(project.id, TaskCreate(title="Эффекты"), owner, db)
    await update_task(
        task.id,
        TaskUpdate.model_validate(
            {"assignee_ids": [str(a.employee_id), str(b.employee_id)]}
        ),
        owner,
        db,
    )
    watchers = set(
        (
            await db.execute(
                select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
            )
        ).scalars()
    )
    assert {a.employee_id, b.employee_id} <= watchers

    members = set(
        (
            await db.execute(
                select(ProjectMember.employee_id).where(
                    ProjectMember.project_id == project.id
                )
            )
        ).scalars()
    )
    assert {a.employee_id, b.employee_id} <= members


async def test_unassign_keeps_watchers_and_membership(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, _b) = await _seed(db, tenant_id, "ma7")
    task = await create_task(
        project.id, TaskCreate(title="Снятие", assignee_ids=[a.employee_id]), owner, db
    )
    await update_task(
        task.id, TaskUpdate.model_validate({"assignee_ids": []}), owner, db
    )
    assert await _assignee_rows(db, task.id) == []
    watchers = set(
        (
            await db.execute(
                select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
            )
        ).scalars()
    )
    assert a.employee_id in watchers
    member = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.employee_id == a.employee_id,
            )
        )
    ).scalar_one_or_none()
    assert member == "viewer"


async def test_reorder_only_writes_no_activity(db: AsyncSession, tenant_id: uuid.UUID):
    """Перестановка меняет position, но не засоряет ленту событием assigned."""
    owner, project, (a, b) = await _seed(db, tenant_id, "ma8")
    task = await create_task(
        project.id,
        TaskCreate(title="Порядок", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    before = len(
        (
            await db.execute(
                select(TaskActivity.id).where(
                    TaskActivity.task_id == task.id, TaskActivity.kind == "assigned"
                )
            )
        ).all()
    )
    await update_task(
        task.id,
        TaskUpdate.model_validate(
            {"assignee_ids": [str(b.employee_id), str(a.employee_id)]}
        ),
        owner,
        db,
    )
    after = len(
        (
            await db.execute(
                select(TaskActivity.id).where(
                    TaskActivity.task_id == task.id, TaskActivity.kind == "assigned"
                )
            )
        ).all()
    )
    assert before == after
    assert await _assignee_rows(db, task.id) == [b.employee_id, a.employee_id]


async def test_activity_payload_has_added_removed_and_legacy_mirror(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "ma9")
    task = await create_task(
        project.id, TaskCreate(title="Лента", assignee_ids=[a.employee_id]), owner, db
    )
    await update_task(
        task.id,
        TaskUpdate.model_validate(
            {"assignee_ids": [str(a.employee_id), str(b.employee_id)]}
        ),
        owner,
        db,
    )
    payload = (
        await db.execute(
            select(TaskActivity.payload)
            .where(TaskActivity.task_id == task.id, TaskActivity.kind == "assigned")
            .order_by(TaskActivity.id.desc())
        )
    ).scalars().first()
    assert payload["added"] == [str(b.employee_id)]
    assert payload["removed"] == []
    assert payload["added_names"] == [b.full_name]
    # Легаси-зеркало для старых бандлов, рендерящих ленту по new.
    assert payload["new"] == str(a.employee_id)


# ─── Инкрементальные ручки ──────────────────────────────────────────────────


async def test_post_assignee_is_idempotent(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, (a, _b) = await _seed(db, tenant_id, "mb1")
    task = await create_task(project.id, TaskCreate(title="Инкремент"), owner, db)
    first = await add_task_assignee(
        task.id, TaskAssigneeAdd(employee_id=a.employee_id), owner, db
    )
    second = await add_task_assignee(
        task.id, TaskAssigneeAdd(employee_id=a.employee_id), owner, db
    )
    assert [x.employee_id for x in first.assignees] == [a.employee_id]
    assert [x.employee_id for x in second.assignees] == [a.employee_id]
    assert await _assignee_rows(db, task.id) == [a.employee_id]


async def test_delete_assignee_is_idempotent(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, (a, _b) = await _seed(db, tenant_id, "mb2")
    task = await create_task(
        project.id, TaskCreate(title="Снять", assignee_ids=[a.employee_id]), owner, db
    )
    await remove_task_assignee(task.id, a.employee_id, owner, db)
    again = await remove_task_assignee(task.id, a.employee_id, owner, db)
    assert again.assignees == []
    assert await _assignee_rows(db, task.id) == []


async def test_concurrent_adds_both_survive(db: AsyncSession, tenant_id: uuid.UUID):
    """Инкрементальный путь не теряет параллельные добавления.

    Регресс на то, ради чего заведены add/remove: replace-семантика с
    устаревшим списком у второго актора затёрла бы первого.
    """
    owner, project, (a, b) = await _seed(db, tenant_id, "mb3")
    task = await create_task(project.id, TaskCreate(title="Гонка"), owner, db)
    await add_task_assignee(task.id, TaskAssigneeAdd(employee_id=a.employee_id), owner, db)
    await add_task_assignee(task.id, TaskAssigneeAdd(employee_id=b.employee_id), owner, db)
    assert await _assignee_rows(db, task.id) == [a.employee_id, b.employee_id]


# ─── Обратная совместимость со старым бандлом ───────────────────────────────


async def test_legacy_assignee_id_patch_still_works(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, _b) = await _seed(db, tenant_id, "mc1")
    task = await create_task(project.id, TaskCreate(title="Легаси"), owner, db)
    updated = await update_task(
        task.id,
        TaskUpdate.model_validate({"assignee_id": str(a.employee_id)}),
        owner,
        db,
    )
    assert [x.employee_id for x in updated.assignees] == [a.employee_id]


async def test_legacy_assignee_id_null_clears_all_assignees(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Осознанное следствие replace-семантики: старый бандл снимает ВСЕХ."""
    owner, project, (a, b) = await _seed(db, tenant_id, "mc2")
    task = await create_task(
        project.id,
        TaskCreate(title="Схлопывание", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    updated = await update_task(
        task.id, TaskUpdate.model_validate({"assignee_id": None}), owner, db
    )
    assert updated.assignees == []


# ─── Регрессы фан-аута и фильтров ───────────────────────────────────────────


async def test_list_tasks_returns_no_duplicate_rows_with_two_assignees(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "md1")
    task = await create_task(
        project.id,
        TaskCreate(title="Без дублей", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    rows = await _list(db, project.id, owner)
    assert [r.id for r in rows].count(task.id) == 1
    assert len(rows[0].assignees) == 2


async def test_list_tasks_filter_assignee_matches_any_of(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "md2")
    task = await create_task(
        project.id,
        TaskCreate(title="Фильтр", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    rows = await _list(db, project.id, owner, assignee_id=b.employee_id)
    assert [r.id for r in rows] == [task.id]


async def test_me_tasks_includes_task_where_i_am_second_assignee(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "md3")
    task = await create_task(
        project.id,
        TaskCreate(title="Мои задачи", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    rows = await list_my_tasks(
        status_=None, due_window=None, include_archived=False, principal=b, db=db
    )
    assert [r.id for r in rows].count(task.id) == 1


async def test_calendar_filter_matches_any_of_without_duplicates(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "md4")
    due = datetime.now(UTC) + timedelta(days=1)
    task = await create_task(
        project.id,
        TaskCreate(
            title="Календарь",
            due_at=due,
            assignee_ids=[a.employee_id, b.employee_id],
        ),
        owner,
        db,
    )
    rows = await list_calendar_tasks(
        project.id,
        from_=(due - timedelta(days=2)).date().isoformat(),
        to=(due + timedelta(days=2)).date().isoformat(),
        status_=None,
        assignee_id=b.employee_id,
        priority=None,
        principal=owner,
        db=db,
    )
    assert [r.id for r in rows] == [task.id]


async def test_workload_counts_task_for_each_assignee_and_keeps_unassigned(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "md5")
    await create_task(
        project.id,
        TaskCreate(title="На двоих", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    await create_task(project.id, TaskCreate(title="Ничья"), owner, db)

    stats = await get_stats(project.id, principal=owner, db=db)
    by_id = {w.employee_id: w for w in stats.workload}
    assert by_id[a.employee_id].active_count == 1
    assert by_id[b.employee_id].active_count == 1
    # Бакет «без исполнителя» переживает INNER JOIN + limit.
    assert by_id[None].active_count == 1


async def test_deleted_employee_hidden_from_response_but_row_survives(
    db: AsyncSession, tenant_id: uuid.UUID
):
    from app.models.shadow import ShadowUser

    owner, project, (a, _b) = await _seed(db, tenant_id, "md6")
    task = await create_task(
        project.id, TaskCreate(title="Уволенный", assignee_ids=[a.employee_id]), owner, db
    )
    su = await db.get(ShadowUser, a.employee_id)
    su.deleted_at = datetime.now(UTC)
    await db.flush()

    fetched = await get_task(task.id, owner, db)
    assert fetched.assignees == []
    assert fetched.assignee_id is None
    # Строка назначения жива — история не переписывается.
    assert await _assignee_rows(db, task.id) == [a.employee_id]
