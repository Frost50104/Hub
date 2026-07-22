"""Per-project RBAC helpers.

In-app roles (`owner | editor | viewer`) live in `project_members.role` —
they're NOT in the JWT. JWT-level role is `hub:admin | member | viewer`:
- `hub:admin` — superuser inside the tenant, bypasses per-project checks.
- `hub:member` — can create projects, then in-app role decides.
- `hub:viewer` — read-only, can't create projects.

API:
    is_hub_admin(principal) -> bool
    can_create_project(principal) -> bool
    fetch_project_or_404(db, project_id) -> Project
    get_my_role(db, project_id, employee_id) -> ProjectRole | None
    require_project_role(
        db, project_id, principal, *, allow=("owner",)
    ) -> tuple[Project, ProjectRole]
        → raises 404 if not visible, 403 if visible but role not in allow.
    capabilities(principal, my_role) -> (can_edit, can_manage)
        → эффективные права для UI; считаются ТОЛЬКО здесь.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember

ProjectRole = Literal["owner", "editor", "viewer"]
HUB_ADMIN_ROLE = "admin"

# Две ступени прав. Держим их РЯДОМ с require_project_role: списки обязаны
# совпадать с `allow=` в ручках, иначе UI снова разъедется с бэкендом.
EDIT_ROLES: tuple[ProjectRole, ...] = ("owner", "editor")
MANAGE_ROLES: tuple[ProjectRole, ...] = ("owner",)


def is_hub_admin(principal: Principal) -> bool:
    return principal.role_for("hub") == HUB_ADMIN_ROLE


def can_create_project(principal: Principal) -> bool:
    role = principal.role_for("hub")
    return role in ("admin", "member")


def capabilities(
    principal: Principal, my_role: ProjectRole | None
) -> tuple[bool, bool]:
    """(can_edit, can_manage) — что вызывающий РЕАЛЬНО может в этом проекте.

    Отдаётся клиенту в ProjectResponse, чтобы фронт не заводил свою копию
    правила: раньше он её завёл, не знал про hub:admin-байпас ниже в
    require_project_role и показывал админу вне членства проект read-only,
    хотя запись сервером разрешена.
    """
    if is_hub_admin(principal):
        return True, True
    return my_role in EDIT_ROLES, my_role in MANAGE_ROLES


async def fetch_project_or_404(db: AsyncSession, project_id: UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return project


async def get_my_role(
    db: AsyncSession, project_id: UUID, employee_id: UUID
) -> ProjectRole | None:
    row = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.employee_id == employee_id,
        )
    )
    return row.scalar_one_or_none()  # type: ignore[return-value]


async def require_project_role(
    db: AsyncSession,
    project_id: UUID,
    principal: Principal,
    *,
    allow: tuple[ProjectRole, ...] = ("owner", "editor", "viewer"),
) -> tuple[Project, ProjectRole | None]:
    """Return the project + caller's role. 404 if invisible, 403 if not enough role.

    `hub:admin` always passes the role check (returns role=None to signal admin
    bypass). For everyone else: must be a project_members entry with role ∈ allow.
    """
    project = await fetch_project_or_404(db, project_id)
    if is_hub_admin(principal):
        return project, None

    my_role = await get_my_role(db, project_id, principal.employee_id)
    if my_role is None:
        # Hide existence from non-members.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    if my_role not in allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Требуется роль {'/'.join(allow)} в проекте",
        )
    return project, my_role
