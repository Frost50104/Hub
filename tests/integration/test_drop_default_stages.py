"""Уборка навязанных стартовых колонок — одноразовая джоба.

Проверяем не «удаляет», а ГРАНИЦУ: раскладку, которую человек трогал, и проект,
в котором уже работают, джоба обязана оставить в покое.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.stages import list_project_stages
from app.api.tasks import create_task
from app.jobs.drop_default_stages import LEGACY_DEFAULT_STAGES, find_candidates
from app.models.stage import ProjectStage
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _project(db: AsyncSession, tenant_id: uuid.UUID, slug: str, name: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=name), owner, db)
    return owner, project


async def _names(db: AsyncSession, project_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(ProjectStage.name)
        .where(ProjectStage.project_id == project_id)
        .order_by(ProjectStage.position)
    )
    return list(rows.scalars().all())


async def test_untouched_default_set_without_tasks_is_a_candidate(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, project = await _project(db, tenant_id, "dds1", "Развитие")
    await seed_stages(db, project.id, owner, names=LEGACY_DEFAULT_STAGES)
    assert await _names(db, project.id) == list(LEGACY_DEFAULT_STAGES)

    candidates = await find_candidates(db)
    assert project.id in [p.id for p, _ in candidates]


async def test_project_with_tasks_is_left_alone(db: AsyncSession, tenant_id: uuid.UUID):
    """Задачи разложены по колонкам — раскладкой пользуются."""
    owner, project = await _project(db, tenant_id, "dds2", "Живой")
    await seed_stages(db, project.id, owner, names=LEGACY_DEFAULT_STAGES)
    await create_task(project.id, TaskCreate(title="Работа"), owner, db)

    candidates = await find_candidates(db)
    assert project.id not in [p.id for p, _ in candidates]


async def test_custom_layout_survives_even_without_tasks(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Проект без задач мог быть ПОДГОТОВЛЕН: свои колонки — это выбор."""
    owner, project = await _project(db, tenant_id, "dds3", "Заготовка")
    await seed_stages(db, project.id, owner, names=("Идея", "Согласование", "Печать"))

    candidates = await find_candidates(db)
    assert project.id not in [p.id for p, _ in candidates]
    assert await _names(db, project.id) == ["Идея", "Согласование", "Печать"]


async def test_renamed_default_column_disqualifies_the_project(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Одно переименование = раскладку трогали. Сравнение — по всей четвёрке."""
    owner, project = await _project(db, tenant_id, "dds4", "Почти дефолт")
    await seed_stages(
        db, project.id, owner, names=("К выполнению", "В работе", "На проверке", "Сдано")
    )

    candidates = await find_candidates(db)
    assert project.id not in [p.id for p, _ in candidates]


async def test_new_project_is_not_a_candidate(db: AsyncSession, tenant_id: uuid.UUID):
    """У нового проекта колонок нет вовсе — чистить нечего, и он не в списке."""
    _owner, project = await _project(db, tenant_id, "dds5", "Новый")
    assert await list_project_stages(project.id, principal=_owner, db=db) == []

    candidates = await find_candidates(db)
    assert project.id not in [p.id for p, _ in candidates]
