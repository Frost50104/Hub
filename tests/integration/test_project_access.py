"""Эффективные права проекта: ProjectResponse.can_edit / can_manage.

Фиксируют контракт «сервер считает права, клиент их рендерит». До этого правило
жило копией и на фронте, копия не знала про hub:admin-байпас в
require_project_role — и админ вне членства видел чужой проект read-only, хотя
запись ему разрешена. Тесты держат обе стороны вместе.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import archive_project, create_project, get_project
from app.api.sections import create_section
from app.models.project import ProjectMember
from app.schemas.project import ProjectCreate
from app.schemas.section import SectionCreate
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _register(db: AsyncSession, principal) -> None:
    """shadow_users/-tenants: доменные FK ссылаются на employee_id."""
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")


async def _project_with_owner(
    db: AsyncSession, tenant_id: uuid.UUID, slug: str
) -> tuple[object, object]:
    """(owner_principal, project) — проект, созданный отдельным сотрудником."""
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)
    return owner, project


async def _add_member(
    db: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, principal, role: str
) -> None:
    db.add(
        ProjectMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            employee_id=principal.employee_id,
            role=role,
            added_by=principal.employee_id,
        )
    )
    await db.commit()


async def test_admin_outside_membership_gets_full_rights(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Регресс из QA: админ видел чужой проект, но UI прятал все контролы."""
    _owner, project = await _project_with_owner(db, tenant_id, "adm")
    admin = make_principal(
        tenant_id, email="admin@t.ru", role="admin", tenant_slug="adm"
    )
    await _register(db, admin)

    resp = await get_project(project.id, admin, db)

    # Членства нет — бейдж роли пустой, но права полные.
    assert resp.my_role is None
    assert resp.can_edit is True
    assert resp.can_manage is True


async def test_admin_outside_membership_can_create_section(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Замыкает контракт: то, что UI теперь показывает, бэкенд реально даёт."""
    _owner, project = await _project_with_owner(db, tenant_id, "adms")
    admin = make_principal(
        tenant_id, email="admin@t.ru", role="admin", tenant_slug="adms"
    )
    await _register(db, admin)

    section = await create_section(
        project.id, SectionCreate(name="Бэклог"), admin, db
    )
    assert section.name == "Бэклог"


async def test_owner_gets_both_flags(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _project_with_owner(db, tenant_id, "own")
    resp = await get_project(project.id, owner, db)
    assert resp.my_role == "owner"
    assert (resp.can_edit, resp.can_manage) == (True, True)


async def test_editor_can_edit_but_not_manage(
    db: AsyncSession, tenant_id: uuid.UUID
):
    _owner, project = await _project_with_owner(db, tenant_id, "edt")
    editor = make_principal(
        tenant_id, email="editor@t.ru", role="member", tenant_slug="edt"
    )
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    resp = await get_project(project.id, editor, db)
    assert resp.my_role == "editor"
    assert (resp.can_edit, resp.can_manage) == (True, False)


async def test_viewer_gets_no_rights(db: AsyncSession, tenant_id: uuid.UUID):
    _owner, project = await _project_with_owner(db, tenant_id, "vwr")
    viewer = make_principal(
        tenant_id, email="viewer@t.ru", role="member", tenant_slug="vwr"
    )
    await _register(db, viewer)
    await _add_member(db, tenant_id, project.id, viewer, "viewer")

    resp = await get_project(project.id, viewer, db)
    assert resp.my_role == "viewer"
    assert (resp.can_edit, resp.can_manage) == (False, False)


async def test_archive_keeps_membership_of_admin_owner(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Админ, который САМ owner проекта, не должен терять роль и избранное.

    require_project_role отдаёт None любому hub:admin (short-circuit до запроса
    членства), поэтому мутирующие ручки обязаны перечитывать membership — иначе
    после архивации бейдж роли и звезда избранного пропадают из кэша клиента.
    """
    admin = make_principal(
        tenant_id, email="boss@t.ru", role="admin", tenant_slug="arc"
    )
    await _register(db, admin)
    project = await create_project(ProjectCreate(name="Свой проект"), admin, db)

    member = await db.get(ProjectMember, (await _sole_member_id(db, project.id)))
    assert member is not None
    member.is_favorite = True
    await db.commit()

    resp = await archive_project(project.id, admin, db)

    assert resp.archived_at is not None
    assert resp.my_role == "owner"
    assert resp.is_favorite is True
    assert (resp.can_edit, resp.can_manage) == (True, True)


async def _sole_member_id(db: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    from sqlalchemy import select

    row = await db.execute(
        select(ProjectMember.id).where(ProjectMember.project_id == project_id)
    )
    return row.scalar_one()
