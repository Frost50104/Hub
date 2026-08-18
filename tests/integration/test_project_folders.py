"""Папки проектов (ОС 17.08).

Ключевые инварианты:
1. Папки ОБЩИЕ для тенанта; CRUD — гейт `can_manage_project_folders`
   (hub admin|member), hub:viewer только читает.
2. Перенос проекта — роль owner в проекте (или hub-admin), как переименование.
3. Удаление папки НИКОГДА не удаляет проекты — они переезжают в «Без папки».
4. `folder_id` присутствует в ОБЕИХ ветках list_projects (admin и member):
   поле объявлено без дефолта, забытая ветка упала бы ValidationError'ом.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.project_folders import (
    create_project_folder,
    delete_project_folder,
    list_project_folders,
    reorder_project_folders,
    update_project_folder,
)
from app.api.projects import create_project, list_projects, set_project_folder
from app.schemas.project import ProjectCreate, ProjectFolderAssign
from app.schemas.project_folder import (
    ProjectFolderCreate,
    ProjectFolderReorder,
    ProjectFolderUpdate,
)
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration


async def _owner(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    p = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, p)
    return p


# ─── Права ──────────────────────────────────────────────────────────────────


async def test_member_can_create_folder(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pf1")
    folder = await create_project_folder(ProjectFolderCreate(name="Маркетинг"), owner, db)
    assert folder.name == "Маркетинг"
    assert folder.position == 0


async def test_viewer_cannot_create_folder(db: AsyncSession, tenant_id: uuid.UUID):
    viewer = make_principal(
        tenant_id, email="v-pf2@t.ru", role="viewer", tenant_slug="pf2"
    )
    await _register(db, viewer)
    with pytest.raises(Exception) as exc:
        await create_project_folder(ProjectFolderCreate(name="Нельзя"), viewer, db)
    assert getattr(exc.value, "status_code", None) == 403


async def test_viewer_sees_folders_readonly(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pf3")
    await create_project_folder(ProjectFolderCreate(name="Общая"), owner, db)
    viewer = make_principal(
        tenant_id, email="v-pf3@t.ru", role="viewer", tenant_slug="pf3"
    )
    await _register(db, viewer)
    listing = await list_project_folders(viewer, db)
    # Containment, а не равенство: под superuser'ом testcontainers RLS не
    # enforced, и выборка видит папки соседних тестов (см. TECH_DEBT,
    # «ловушка testcontainers-superuser»). В проде их отрезает политика.
    assert "Общая" in [f.name for f in listing.folders]
    assert listing.can_manage is False


async def test_admin_can_manage_folders(db: AsyncSession, tenant_id: uuid.UUID):
    admin = make_principal(
        tenant_id, email="a-pf4@t.ru", role="admin", tenant_slug="pf4"
    )
    await _register(db, admin)
    assert (await list_project_folders(admin, db)).can_manage is True


# ─── Папки ──────────────────────────────────────────────────────────────────


async def test_duplicate_folder_name_conflicts(db: AsyncSession, tenant_id: uuid.UUID):
    """Регистронезависимо: две «Маркетинг» в общем дереве неразличимы."""
    owner = await _owner(db, tenant_id, "pf5")
    await create_project_folder(ProjectFolderCreate(name="Маркетинг"), owner, db)
    with pytest.raises(Exception) as exc:
        await create_project_folder(ProjectFolderCreate(name="маркетинг"), owner, db)
    assert getattr(exc.value, "status_code", None) == 409


async def test_second_folder_appends_position(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pf6")
    first = await create_project_folder(ProjectFolderCreate(name="Первая"), owner, db)
    second = await create_project_folder(ProjectFolderCreate(name="Вторая"), owner, db)
    # Относительно первой: абсолютное значение зависит от папок соседних
    # тестов (RLS под superuser'ом не enforced).
    assert second.position == first.position + 1


async def test_rename_folder(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pf7")
    folder = await create_project_folder(ProjectFolderCreate(name="Старое"), owner, db)
    renamed = await update_project_folder(
        folder.id, ProjectFolderUpdate(name="Новое"), owner, db
    )
    assert renamed.name == "Новое"


async def test_reorder_folders_rewrites_positions(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner = await _owner(db, tenant_id, "pf8")
    a = await create_project_folder(ProjectFolderCreate(name="А"), owner, db)
    b = await create_project_folder(ProjectFolderCreate(name="Б"), owner, db)
    out = await reorder_project_folders(
        ProjectFolderReorder(folder_ids=[b.id, a.id]), owner, db
    )
    ids = [f.id for f in out]
    assert ids.index(b.id) < ids.index(a.id)
    by_id = {f.id: f for f in out}
    assert by_id[b.id].position == 0
    assert by_id[a.id].position == 1


async def test_delete_unknown_folder_404(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pf9")
    with pytest.raises(Exception) as exc:
        await delete_project_folder(uuid.uuid4(), owner, db)
    assert getattr(exc.value, "status_code", None) == 404


# ─── Перенос проекта ────────────────────────────────────────────────────────


async def test_owner_moves_project_into_folder(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pg1")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Папка"), owner, db)

    moved = await set_project_folder(
        project.id, ProjectFolderAssign(folder_id=folder.id), owner, db
    )
    assert moved.folder_id == folder.id
    listing = await list_projects(include_archived=False, principal=owner, db=db)
    assert next(p for p in listing if p.id == project.id).folder_id == folder.id


async def test_move_to_null_unfiles_project(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pg2")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Папка"), owner, db)
    await set_project_folder(
        project.id, ProjectFolderAssign(folder_id=folder.id), owner, db
    )
    back = await set_project_folder(
        project.id, ProjectFolderAssign(folder_id=None), owner, db
    )
    assert back.folder_id is None


async def test_editor_cannot_move_project(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pg3")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Папка"), owner, db)

    editor = make_principal(
        tenant_id, email="ed-pg3@t.ru", role="member", tenant_slug="pg3"
    )
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    with pytest.raises(Exception) as exc:
        await set_project_folder(
            project.id, ProjectFolderAssign(folder_id=folder.id), editor, db
        )
    assert getattr(exc.value, "status_code", None) == 403


async def test_non_member_move_gets_404(db: AsyncSession, tenant_id: uuid.UUID):
    """Существование проекта скрыто от не-участника — 404, а не 403."""
    owner = await _owner(db, tenant_id, "pg4")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Папка"), owner, db)

    stranger = make_principal(
        tenant_id, email="st-pg4@t.ru", role="member", tenant_slug="pg4"
    )
    await _register(db, stranger)
    with pytest.raises(Exception) as exc:
        await set_project_folder(
            project.id, ProjectFolderAssign(folder_id=folder.id), stranger, db
        )
    assert getattr(exc.value, "status_code", None) == 404


async def test_hub_admin_moves_project_without_membership(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner = await _owner(db, tenant_id, "pg5")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Папка"), owner, db)

    admin = make_principal(
        tenant_id, email="ad-pg5@t.ru", role="admin", tenant_slug="pg5"
    )
    await _register(db, admin)
    moved = await set_project_folder(
        project.id, ProjectFolderAssign(folder_id=folder.id), admin, db
    )
    assert moved.folder_id == folder.id


async def test_move_to_unknown_folder_404(db: AsyncSession, tenant_id: uuid.UUID):
    owner = await _owner(db, tenant_id, "pg6")
    project = await create_project(ProjectCreate(name="Проект"), owner, db)
    with pytest.raises(Exception) as exc:
        await set_project_folder(
            project.id, ProjectFolderAssign(folder_id=uuid.uuid4()), owner, db
        )
    assert getattr(exc.value, "status_code", None) == 404


# ─── Главный инвариант ──────────────────────────────────────────────────────


async def test_delete_folder_keeps_projects_and_unfiles_them(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """FK ON DELETE SET NULL: удаление папки не должно трогать проекты."""
    owner = await _owner(db, tenant_id, "ph1")
    project = await create_project(ProjectCreate(name="Живучий"), owner, db)
    folder = await create_project_folder(ProjectFolderCreate(name="Временная"), owner, db)
    await set_project_folder(
        project.id, ProjectFolderAssign(folder_id=folder.id), owner, db
    )

    await delete_project_folder(folder.id, owner, db)

    listing = await list_projects(include_archived=False, principal=owner, db=db)
    survivor = next(p for p in listing if p.id == project.id)
    assert survivor.folder_id is None


# ─── Контракт списка ────────────────────────────────────────────────────────


async def test_list_projects_includes_folder_id_for_member_branch(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner = await _owner(db, tenant_id, "pi1")
    await create_project(ProjectCreate(name="Мембер"), owner, db)
    listing = await list_projects(include_archived=False, principal=owner, db=db)
    assert all(hasattr(p, "folder_id") for p in listing)


async def test_list_projects_includes_folder_id_for_admin_branch(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner = await _owner(db, tenant_id, "pi2")
    await create_project(ProjectCreate(name="Админ"), owner, db)
    admin = make_principal(
        tenant_id, email="ad-pi2@t.ru", role="admin", tenant_slug="pi2"
    )
    await _register(db, admin)
    listing = await list_projects(include_archived=False, principal=admin, db=db)
    assert all(hasattr(p, "folder_id") for p in listing)
