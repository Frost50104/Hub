"""Получатели напоминаний due_soon/overdue (0034).

Логика вынесена из джобов в `collect_recipients`, потому что сами джобы
(main()) не покрыты тестами: до 0034 «исполнитель» брался из колонки одной
строкой, и пропуск вторичных исполнителей был бы тихой потерей уведомлений.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.tasks import create_task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.services.task_assignees import collect_recipients
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Джобы {slug}"), owner, db)
    people = []
    for i in range(2):
        p = make_principal(
            tenant_id, email=f"u{i}-{slug}@t.ru", role="member", tenant_slug=slug
        )
        await _register(db, p)
        people.append(p)
    return owner, project, people


async def test_collect_recipients_unions_watchers_and_assignees(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project, (a, b) = await _seed(db, tenant_id, "jr1")
    task = await create_task(
        project.id,
        TaskCreate(title="Напоминание", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    recipients = await collect_recipients(db, [task.id])
    # Создатель попадает как watcher, оба исполнителя — как assignees.
    assert {owner.employee_id, a.employee_id, b.employee_id} <= recipients[task.id]


async def test_collect_recipients_includes_secondary_assignee(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Второй исполнитель обязан получать напоминания наравне с первым."""
    owner, project, (a, b) = await _seed(db, tenant_id, "jr2")
    task = await create_task(
        project.id,
        TaskCreate(title="Второй", assignee_ids=[a.employee_id, b.employee_id]),
        owner,
        db,
    )
    assert b.employee_id in (await collect_recipients(db, [task.id]))[task.id]


async def test_collect_recipients_empty_input(db: AsyncSession, tenant_id: uuid.UUID):
    assert await collect_recipients(db, []) == {}
