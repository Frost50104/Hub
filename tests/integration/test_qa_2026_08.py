"""Регресс-тесты фиксов предрелизного QA-прогона 2026-08-21
(docs/tech-debt/qa-2026-08.md): #23 PATCH сотрудника без орг-полей,
#20 состав группы → аудитория без ручного rebuild, #21 кто создаёт проекты и
папки, #18 ?preview=1 у урока."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import get_lesson
from app.api.employees import update_employee
from app.api.org import _GROUP_KINDS, replace_group_members
from app.api.project_folders import (
    create_project_folder,
    delete_project_folder,
    list_project_folders,
)
from app.api.projects import create_project
from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, UserGroup
from app.schemas.employee import EmployeeUpdate
from app.schemas.org import GroupMembersReplace
from app.schemas.project import ProjectCreate
from app.schemas.project_folder import ProjectFolderCreate
from app.services.project_access import (
    CREATE_PROJECT_DENIED,
    can_create_project,
)
from tests.integration.conftest import make_principal
from tests.integration.test_courses import _mk_course
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_redis_no_push(monkeypatch):
    async def _noop_rate_limit(**kw) -> None:
        return None

    from app.api import courses as courses_api
    from app.services import notify_batch

    monkeypatch.setattr(courses_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(notify_batch, "schedule_push_batch", lambda batch: None)


def _slug(tenant_id: uuid.UUID, tag: str) -> str:
    return f"qa-{tag}-{tenant_id.hex[:8]}"


async def _admin(db: AsyncSession, tenant_id: uuid.UUID, tag: str):
    admin = make_principal(
        tenant_id, email=f"admin-{tag}@t.ru", role="admin", tenant_slug=_slug(tenant_id, tag)
    )
    await _register(db, admin)
    return admin


async def _mk_profile(db: AsyncSession, tenant_id: uuid.UUID, email: str, **kw) -> EmployeeProfile:
    profile = EmployeeProfile(tenant_id=tenant_id, email=email, full_name=email.split("@")[0], **kw)
    db.add(profile)
    await db.flush()
    return profile


# ─── #23 PATCH /learn/employees/{id} без орг-полей ──────────────────────────


async def test_patch_employee_content_role_only_is_200(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "e1")
    profile = await _mk_profile(db, tenant_id, "pub@t.ru")
    resp = await update_employee(profile.id, EmployeeUpdate(content_role="publisher"), admin, db)
    assert resp.content_role == "publisher"
    resp2 = await update_employee(
        profile.id, EmployeeUpdate(phone="+7 900 000-00-00", status_text="в отпуске"), admin, db
    )
    assert resp2.phone == "+7 900 000-00-00"


async def test_patch_archived_profile_org_field_is_200(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "e2")
    position = Position(tenant_id=tenant_id, name="Бариста")
    db.add(position)
    await db.flush()
    profile = await _mk_profile(db, tenant_id, "arch@t.ru", status="archived")
    resp = await update_employee(profile.id, EmployeeUpdate(position_id=position.id), admin, db)
    assert resp.position_id == position.id


# ─── #20 состав группы → audience_members в том же запросе ──────────────────


async def test_group_members_replace_recalcs_audience(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "g1")
    group = UserGroup(tenant_id=tenant_id, name="QA-группа")
    db.add(group)
    await db.flush()
    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            user_group_ids=[group.id],
        )
    )
    newcomer = await _mk_profile(db, tenant_id, "new@t.ru")
    await db.flush()
    kind = next(k for k, v in _GROUP_KINDS.items() if v[0] is UserGroup)

    await replace_group_members(
        kind, group.id, GroupMembersReplace(member_ids=[newcomer.id]), admin, db
    )
    members = {
        r[0]
        for r in await db.execute(
            select(AudienceMember.profile_id).where(AudienceMember.audience_id == audience.id)
        )
    }
    assert newcomer.id in members

    await replace_group_members(kind, group.id, GroupMembersReplace(member_ids=[]), admin, db)
    members = {
        r[0]
        for r in await db.execute(
            select(AudienceMember.profile_id).where(AudienceMember.audience_id == audience.id)
        )
    }
    assert newcomer.id not in members


# ─── #21 кто создаёт проекты и папки ────────────────────────────────────────


async def _member(db: AsyncSession, tenant_id: uuid.UUID, tag: str, org_role: str | None):
    p = make_principal(
        tenant_id, email=f"m-{tag}@t.ru", role="member", tenant_slug=_slug(tenant_id, tag)
    )
    await _register(db, p, org_role=org_role)
    return p


@pytest.mark.parametrize("org_role", ["office", "tu", "franchisee_owner"])
async def test_org_roles_can_create_project_and_folder(
    db: AsyncSession, tenant_id: uuid.UUID, org_role: str
):
    p = await _member(db, tenant_id, f"ok-{org_role}", org_role)
    assert await can_create_project(db, p) is True
    project = await create_project(ProjectCreate(name=f"Проект {org_role}"), p, db)
    assert project.can_manage is True
    assert (await list_project_folders(p, db)).can_manage is True
    # Папку создаём и тут же удаляем: под superuser'ом testcontainers RLS не
    # enforced, и лишние папки сдвигали бы position в test_project_folders.
    folder = await create_project_folder(
        ProjectFolderCreate(name=f"Папка {org_role}"), p, db
    )
    assert folder.name == f"Папка {org_role}"
    await delete_project_folder(folder.id, p, db)


async def test_line_employee_cannot_create_project_or_folder(
    db: AsyncSession, tenant_id: uuid.UUID
):
    p = await _member(db, tenant_id, "emp", "employee")
    assert await can_create_project(db, p) is False
    with pytest.raises(HTTPException) as exc:
        await create_project(ProjectCreate(name="Нельзя"), p, db)
    assert exc.value.status_code == 403
    assert exc.value.detail == CREATE_PROJECT_DENIED
    with pytest.raises(HTTPException) as exc2:
        await create_project_folder(ProjectFolderCreate(name="Нельзя"), p, db)
    assert exc2.value.status_code == 403
    assert (await list_project_folders(p, db)).can_manage is False


async def test_member_without_profile_and_archived_cannot_create(
    db: AsyncSession, tenant_id: uuid.UUID
):
    no_profile = await _member(db, tenant_id, "nop", None)
    assert await can_create_project(db, no_profile) is False
    archived = make_principal(
        tenant_id, email="arch-m@t.ru", role="member", tenant_slug=_slug(tenant_id, "arc")
    )
    await _register(db, archived)
    await _mk_profile(
        db,
        tenant_id,
        archived.email,
        employee_id=archived.employee_id,
        org_role="office",
        status="archived",
    )
    assert await can_create_project(db, archived) is False


async def test_admin_and_viewer_create_rights(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "av")
    assert await can_create_project(db, admin) is True
    viewer = make_principal(
        tenant_id, email="v@t.ru", role="viewer", tenant_slug=_slug(tenant_id, "vw")
    )
    await _register(db, viewer, org_role="office")
    assert await can_create_project(db, viewer) is False


# ─── #18 ?preview=1 у урока ─────────────────────────────────────────────────


async def test_lesson_preview_applies_locks_to_manager(db: AsyncSession, tenant_id: uuid.UUID):
    admin = await _admin(db, tenant_id, "lp")
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=2)

    # Автор/админ без preview: урок 2 открыт, «Следующий» не заперт.
    resp = await get_lesson(lessons[0].id, admin, db)
    assert resp.next_locked is False
    assert (await get_lesson(lessons[1].id, admin, db)).id == lessons[1].id

    # Глазами сотрудника: замки как у обычного профиля.
    resp_preview = await get_lesson(lessons[0].id, admin, db, preview=True)
    assert resp_preview.next_locked is True
    with pytest.raises(HTTPException) as exc:
        await get_lesson(lessons[1].id, admin, db, preview=True)
    assert exc.value.status_code == 403
