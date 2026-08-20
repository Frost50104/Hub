"""Хронология: окно задач и флаг `include_undated` (редизайн 2026-08).

Гант рисует строку для задачи без срока («строка есть, полосы нет») и считает
«N без срока» — для этого API по явной просьбе отдаёт и недатированные задачи.
Без флага поведение прежнее: только задачи, пересекающие окно.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.tasks import create_task
from app.api.timeline import get_timeline
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
    project = await create_project(ProjectCreate(name=f"Timeline {slug}"), owner, db)
    return owner, project


async def test_undated_tasks_only_with_flag(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "tl1")
    now = datetime.now(UTC)
    dated = await create_task(
        project.id, TaskCreate(title="Со сроком", due_at=now + timedelta(days=2)), owner, db
    )
    undated = await create_task(project.id, TaskCreate(title="Без срока"), owner, db)
    far = await create_task(
        project.id, TaskCreate(title="Далеко", due_at=now + timedelta(days=60)), owner, db
    )
    from_ = (now - timedelta(days=7)).date().isoformat()
    to = (now + timedelta(days=30)).date().isoformat()

    plain = await get_timeline(
        project.id, from_=from_, to=to, include_undated=False, principal=owner, db=db
    )
    ids = {t.id for t in plain.tasks}
    assert dated.id in ids
    assert undated.id not in ids, "без флага недатированные не приходят (старые бандлы)"
    assert far.id not in ids, "задача вне окна не приходит"

    full = await get_timeline(
        project.id, from_=from_, to=to, include_undated=True, principal=owner, db=db
    )
    ids = {t.id for t in full.tasks}
    assert dated.id in ids
    assert undated.id in ids, "с флагом строка без полосы есть"
    assert far.id not in ids, "флаг добавляет только задачи БЕЗ срока, не вне окна"
    assert next(t for t in full.tasks if t.id == undated.id).due_at is None
