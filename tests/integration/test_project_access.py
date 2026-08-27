"""Эффективные права проекта: ProjectResponse.can_edit / can_manage.

Фиксируют контракт «сервер считает права, клиент их рендерит». До этого правило
жило копией и на фронте, копия не знала про hub:admin-байпас в
require_project_role — и админ вне членства видел чужой проект read-only, хотя
запись ему разрешена. Тесты держат обе стороны вместе.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import (
    add_member,
    archive_project,
    create_project,
    delete_project,
    get_project,
    unarchive_project,
    update_project,
)
from app.models.employee_profile import EmployeeProfile
from app.models.project import ProjectMember
from app.schemas.project import ProjectCreate, ProjectMemberAdd, ProjectUpdate
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _register(
    db: AsyncSession, principal, *, org_role: str | None = None
) -> None:
    """shadow_users/-tenants: доменные FK ссылаются на employee_id.

    org_role — создать активный learn-профиль с этой орг-ролью: с 2026-08-21
    hub:member создаёт проекты/папки ТОЛЬКО как офис/ТУ/франчайзи
    (`project_access.can_create_project`), поэтому владельцы проектов в тестах
    регистрируются с `org_role="office"`.
    """
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    if org_role is not None:
        db.add(
            EmployeeProfile(
                tenant_id=principal.tenant_id,
                employee_id=principal.employee_id,
                email=principal.email,
                full_name=principal.full_name,
                org_role=org_role,
            )
        )
        await db.flush()


async def _project_with_owner(
    db: AsyncSession, tenant_id: uuid.UUID, slug: str
) -> tuple[object, object]:
    """(owner_principal, project) — проект, созданный отдельным сотрудником."""
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
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


# ─── Профиль проекта правит редактор (27.08) ────────────────────────────────
#
# До этого PATCH и обе ручки бейджа требовали владельца, и редактор — на проде
# это сотрудницы, ведущие 13 проектов, — не мог исправить даже опечатку в
# названии. Гейт стал edit-tier, то есть совпал с тем, что клиенту обещает
# `can_edit`. Тесты ниже держат ОБЕ границы: что открылось и что осталось
# закрытым, потому что послабление легко «заодно» протащить в управление.


async def _member(db: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, role: str):
    slug = uuid.uuid4().hex[:6]
    principal = make_principal(
        tenant_id, email=f"{role}-{slug}@t.ru", tenant_slug=f"{role}{slug}"
    )
    await _register(db, principal)
    await _add_member(db, tenant_id, project_id, principal, role)
    return principal


async def test_editor_can_rename_project(db: AsyncSession, tenant_id: uuid.UUID):
    _owner, project = await _project_with_owner(db, tenant_id, "ren")
    editor = await _member(db, tenant_id, project.id, "editor")

    resp = await update_project(project.id, ProjectUpdate(name="Новое имя"), editor, db)
    assert resp.name == "Новое имя"


async def test_editor_can_clear_description(db: AsyncSession, tenant_id: uuid.UUID):
    """Пустая строка стирает, `None` означает «не менять» — пинаем идиому."""
    _owner, project = await _project_with_owner(db, tenant_id, "clr")
    editor = await _member(db, tenant_id, project.id, "editor")
    await update_project(project.id, ProjectUpdate(description="было"), editor, db)

    resp = await update_project(project.id, ProjectUpdate(description=""), editor, db)
    assert resp.description == ""


async def test_viewer_cannot_update_project(db: AsyncSession, tenant_id: uuid.UUID):
    """Граница, которая не должна съехать вместе с послаблением."""
    _owner, project = await _project_with_owner(db, tenant_id, "vw")
    viewer = await _member(db, tenant_id, project.id, "viewer")

    with pytest.raises(HTTPException) as exc:
        await update_project(project.id, ProjectUpdate(name="Нельзя"), viewer, db)
    assert exc.value.status_code == 403


async def test_stranger_gets_404_not_403(db: AsyncSession, tenant_id: uuid.UUID):
    """Посторонний не должен узнать, что проект существует."""
    _owner, project = await _project_with_owner(db, tenant_id, "str")
    slug = uuid.uuid4().hex[:6]
    stranger = make_principal(
        tenant_id, email=f"str-{slug}@t.ru", tenant_slug=f"str{slug}"
    )
    await _register(db, stranger)

    with pytest.raises(HTTPException) as exc:
        await update_project(project.id, ProjectUpdate(name="Нельзя"), stranger, db)
    assert exc.value.status_code == 404


async def test_editor_cannot_archive_or_unarchive(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Архив прячет проект у ВСЕЙ команды — остаётся у владельца."""
    _owner, project = await _project_with_owner(db, tenant_id, "arch")
    editor = await _member(db, tenant_id, project.id, "editor")

    for handler in (archive_project, unarchive_project):
        with pytest.raises(HTTPException) as exc:
            await handler(project.id, editor, db)
        assert exc.value.status_code == 403


async def test_editor_cannot_delete_project(db: AsyncSession, tenant_id: uuid.UUID):
    _owner, project = await _project_with_owner(db, tenant_id, "del")
    editor = await _member(db, tenant_id, project.id, "editor")

    with pytest.raises(HTTPException) as exc:
        await delete_project(project.id, key=project.key, principal=editor, db=db)
    assert exc.value.status_code == 403


async def test_editor_cannot_add_member(db: AsyncSession, tenant_id: uuid.UUID):
    """Доказывает, что послабление не протекло в управление доступом."""
    _owner, project = await _project_with_owner(db, tenant_id, "mem")
    editor = await _member(db, tenant_id, project.id, "editor")
    outsider = await _member(db, tenant_id, project.id, "viewer")

    with pytest.raises(HTTPException) as exc:
        await add_member(
            project.id,
            ProjectMemberAdd(employee_id=outsider.employee_id, role="editor"),
            editor,
            db,
        )
    assert exc.value.status_code == 403


async def test_admin_outside_membership_renames_and_keeps_null_role(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Сторожит перечитывание членства: require_project_role отдаёт None
    ЛЮБОМУ админу, и брать роль из неё для ответа нельзя."""
    _owner, project = await _project_with_owner(db, tenant_id, "adm2")
    slug = uuid.uuid4().hex[:6]
    admin = make_principal(
        tenant_id, email=f"adm-{slug}@t.ru", role="admin", tenant_slug=f"adm{slug}"
    )
    await _register(db, admin)

    resp = await update_project(project.id, ProjectUpdate(name="От админа"), admin, db)
    assert resp.name == "От админа"
    assert resp.my_role is None
    assert resp.can_edit and resp.can_manage


async def test_editor_update_is_audited(db: AsyncSession, tenant_id: uuid.UUID):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    _owner, project = await _project_with_owner(db, tenant_id, "aud")
    editor = await _member(db, tenant_id, project.id, "editor")

    await update_project(project.id, ProjectUpdate(name="Переименовано"), editor, db)

    row = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.object_type == "project", AuditLog.object_id == project.id)
            .order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert row is not None
    assert row.action == "update"
    assert row.actor_id == editor.employee_id
