"""Номера задач «KEY-42» (0032): атомарная выдача seq + прокидка в ответы.

Счётчик projects.next_task_seq выдаётся UPDATE...RETURNING под row-lock —
конкурентные создания сериализуются без retry; UNIQUE(project_id, seq) —
страховочная сетка. Backfill-SQL миграции проверяется на живых данных
(идемпотентность нумерации по created_at, id).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.me_tasks import list_my_tasks
from app.api.projects import create_project
from app.api.search import search
from app.api.tasks import create_task
from app.models.project import Project
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Seq {slug}"), owner, db)
    return owner, project


async def test_seq_monotonic_and_counter(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "seq1")

    seqs = []
    for i in range(3):
        task = await create_task(project.id, TaskCreate(title=f"Задача {i}"), owner, db)
        seqs.append(task.seq)
    assert seqs == [1, 2, 3]

    next_seq = (
        await db.execute(
            select(Project.next_task_seq).where(Project.id == project.id)
        )
    ).scalar_one()
    assert next_seq == 4


async def test_seq_isolated_per_project(db: AsyncSession, tenant_id: uuid.UUID):
    owner_a, project_a = await _seed(db, tenant_id, "seqa")
    owner_b, project_b = await _seed(db, tenant_id, "seqb")

    task_a = await create_task(project_a.id, TaskCreate(title="A1"), owner_a, db)
    task_b = await create_task(project_b.id, TaskCreate(title="B1"), owner_b, db)

    assert task_a.seq == 1
    assert task_b.seq == 1


async def test_concurrent_creates_get_unique_seq(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Row-lock счётчика сериализует конкурентные создания (две сессии)."""
    from app.db import tenant_scoped_session

    owner, project = await _seed(db, tenant_id, "seqc")
    await db.commit()  # проект должен быть виден другим соединениям

    async def _create(n: int) -> int:
        async with tenant_scoped_session(tenant_id) as session:
            task = await create_task(
                project.id, TaskCreate(title=f"Гонка {n}"), owner, session
            )
            return task.seq

    got = await asyncio.gather(_create(1), _create(2))
    assert sorted(got) == [1, 2]


async def test_backfill_sql_numbers_by_created_at(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """CTE из 0032 нумерует детерминированно по (created_at, id)."""
    owner, project = await _seed(db, tenant_id, "seqbf")
    t1 = await create_task(project.id, TaskCreate(title="Первая"), owner, db)
    t2 = await create_task(project.id, TaskCreate(title="Вторая"), owner, db)

    # Имитируем до-миграционное состояние: NOT NULL не даёт занулить —
    # сдвигаем номера в «мусорный» диапазон и перенумеровываем CTE из 0032.
    await db.execute(
        sa_text("UPDATE tasks SET seq = seq + 1000 WHERE project_id = :pid").bindparams(
            pid=project.id
        )
    )
    await db.execute(
        sa_text(
            """
            WITH numbered AS (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY project_id ORDER BY created_at, id
                ) AS rn
                FROM tasks WHERE project_id = :pid
            )
            UPDATE tasks t SET seq = n.rn FROM numbered n WHERE t.id = n.id
            """
        ).bindparams(pid=project.id)
    )
    rows = (
        await db.execute(
            sa_text(
                "SELECT id, seq FROM tasks WHERE project_id = :pid ORDER BY created_at, id"
            ).bindparams(pid=project.id)
        )
    ).all()
    assert [r.seq for r in rows] == [1, 2]
    assert {str(r.id) for r in rows} == {str(t1.id), str(t2.id)}


async def test_me_tasks_returns_project_key(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "seqme")
    await create_task(
        project.id,
        TaskCreate(title="Моя", assignee_id=owner.employee_id),
        owner,
        db,
    )

    items = await list_my_tasks(
        status_=None,
        due_window=None,
        include_archived=False,
        principal=owner,
        db=db,
    )
    assert len(items) == 1
    assert items[0].seq == 1
    assert items[0].project_key == project.key


async def test_search_hits_carry_seq(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "seqsr")
    task = await create_task(
        project.id, TaskCreate(title="Онбординг курьеров"), owner, db
    )

    grouped = await search(
        q="онбординг", group_by="project", principal=owner, db=db
    )
    hit = grouped.groups[0].tasks[0]
    assert hit.id == task.id
    assert hit.seq == task.seq

    legacy = await search(q="онбординг", group_by=None, principal=owner, db=db)
    legacy_hit = next(h for h in legacy.tasks if h.id == task.id)
    assert legacy_hit.seq == task.seq
    assert legacy_hit.project_key == project.key
