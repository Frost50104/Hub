"""Метаданные ЧУЖОГО личного проекта гостю не отдаются.

Приглашённый в личное пространство (исполнитель поручения или наблюдатель)
видит там ровно свои задачи — это держит `personal_task_scope` в `list_tasks` и
`require_task_access`. Но пять соседних ручек скоуп не применяли и отдавали
гостю всё: метки владельца, его колонки вместе со счётчиками задач,
определения кастом-полей, ЗНАЧЕНИЯ полей всех задач проекта и полный список
участников. Докстринг `personal_projects` при этом утверждал обратное.

Правка 16.09: метки/колонки/определения — пустой список (их зовёт карточка
задачи, и 403 дал бы гостю тост об ошибке), значения и участники — 403, как
остальные агрегаты по всем задачам.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.custom_fields import (
    create_custom_field,
    list_custom_fields,
    list_project_custom_values,
)
from app.api.labels import create_label, list_labels
from app.api.me_delegate import DelegateCreate, delegate_personal_task
from app.api.projects import list_members
from app.api.stages import list_project_stages
from app.api.tasks import create_task
from app.schemas.custom_field import CustomFieldDefinitionCreate
from app.schemas.label import LabelCreate
from app.schemas.task import TaskCreate
from app.services.personal_projects import ensure_personal_project
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _member(db: AsyncSession, tenant_id: uuid.UUID, slug: str) -> Principal:
    principal = make_principal(
        tenant_id, email=f"{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, principal, org_role="office")
    return principal


@pytest.fixture
async def guest_in_personal(db: AsyncSession, tenant_id: uuid.UUID):
    """(владелец, гость, id личного). Гость приглашён поручением."""
    # Слаг уникален на КАЖДЫЙ прогон фикстуры: `upsert_shadow_tenant` пишет
    # его с UNIQUE-индексом, а фикстура функциональная и бежит на каждый тест.
    tag = uuid.uuid4().hex[:8]
    owner = await _member(db, tenant_id, f"pv-{tag}-o")
    guest = await _member(db, tenant_id, f"pv-{tag}-g")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    # Личные дела владельца, которых гость видеть не должен.
    await create_task(personal_id, TaskCreate(title="Записаться к врачу"), owner, db)
    await create_label(personal_id, LabelCreate(name="Здоровье"), owner, db)
    await create_custom_field(
        personal_id,
        CustomFieldDefinitionCreate(name="Клиника", type="text"),
        owner,
        db,
    )
    await db.commit()

    # Гость приходит сюда единственным законным путём — с поручением.
    await delegate_personal_task(
        DelegateCreate(employee_id=owner.employee_id, title="Забрать акты"),
        guest,
        db,
    )
    await db.commit()
    return owner, guest, personal_id


async def test_guest_gets_empty_metadata(db, guest_in_personal):
    """Метки, колонки и определения полей — пусто, но не ошибка."""
    _owner, guest, personal_id = guest_in_personal

    assert await list_labels(personal_id, guest, db) == []
    assert await list_project_stages(personal_id, guest, db) == []
    assert await list_custom_fields(personal_id, guest, db) == []


async def test_guest_blocked_from_values_and_members(db, guest_in_personal):
    """Значения полей всех задач и состав участников — 403."""
    _owner, guest, personal_id = guest_in_personal

    for call in (
        lambda: list_project_custom_values(personal_id, guest, db),
        lambda: list_members(personal_id, guest, db),
    ):
        with pytest.raises(HTTPException) as err:
            await call()
        assert err.value.status_code == 403


async def test_owner_still_sees_everything(db, guest_in_personal):
    """Анти-регресс: владельцу своё личное отдаётся целиком."""
    owner, _guest, personal_id = guest_in_personal

    assert [x.name for x in await list_labels(personal_id, owner, db)] == ["Здоровье"]
    assert [x.name for x in await list_custom_fields(personal_id, owner, db)] == [
        "Клиника"
    ]
    # Колонок у личного проекта нет по построению (0046) — важно, что не 403.
    assert await list_project_stages(personal_id, owner, db) == []
    assert await list_project_custom_values(personal_id, owner, db) == []
    members = {m.employee_id for m in await list_members(personal_id, owner, db)}
    assert owner.employee_id in members


async def test_work_project_metadata_untouched(db, tenant_id):
    """Регресс: в ОБЫЧНОМ проекте viewer по-прежнему видит метаданные.

    Гейт стоит на «чужое личное», а не на «я не редактор» — иначе наблюдатель
    рабочего проекта потерял бы фильтр по меткам и имена колонок в карточке.
    """
    from app.api.projects import create_project
    from app.schemas.project import ProjectCreate
    from app.services.project_access import ensure_project_member

    tag = uuid.uuid4().hex[:8]
    owner = await _member(db, tenant_id, f"pvw-{tag}-o")
    viewer = await _member(db, tenant_id, f"pvw-{tag}-v")
    project = await create_project(ProjectCreate(name="Рабочий"), owner, db)
    await create_label(project.id, LabelCreate(name="Срочно"), owner, db)
    await ensure_project_member(
        db,
        project_id=project.id,
        tenant_id=tenant_id,
        employee_id=viewer.employee_id,
        added_by=owner.employee_id,
    )
    await db.commit()

    assert [x.name for x in await list_labels(project.id, viewer, db)] == ["Срочно"]
    assert len(await list_members(project.id, viewer, db)) == 2
