"""Projects + project_members API."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.schemas.project import (
    ProjectCreate,
    ProjectFavoriteUpdate,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project_access import (
    can_create_project,
    fetch_project_or_404,
    is_hub_admin,
    require_project_role,
)
from app.services.project_key import generate_unique_key

router = APIRouter(tags=["projects"])


def _project_to_response(
    project: Project, my_role: str | None, is_favorite: bool = False
) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        key=project.key,
        name=project.name,
        description=project.description,
        archived_at=project.archived_at,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,  # type: ignore[arg-type]
        is_favorite=is_favorite,
    )


async def _my_membership(
    db: AsyncSession, project_id: UUID, employee_id: UUID
) -> tuple[str | None, bool]:
    """(role, is_favorite) текущего пользователя; (None, False) вне членства."""
    row = (
        await db.execute(
            select(ProjectMember.role, ProjectMember.is_favorite).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == employee_id,
            )
        )
    ).first()
    if row is None:
        return None, False
    return row.role, row.is_favorite


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    # hub:admin sees every project in the tenant; everyone else only those
    # they're a member of. RLS already restricts to tenant scope.
    if is_hub_admin(principal):
        stmt = select(Project)
        if not include_archived:
            stmt = stmt.where(Project.archived_at.is_(None))
        rows = (await db.execute(stmt.order_by(Project.created_at.desc()))).scalars().all()
        # Bulk-load my_role + is_favorite so admin still sees their state.
        if rows:
            roles_q = await db.execute(
                select(
                    ProjectMember.project_id,
                    ProjectMember.role,
                    ProjectMember.is_favorite,
                ).where(
                    ProjectMember.employee_id == principal.employee_id,
                    ProjectMember.project_id.in_([p.id for p in rows]),
                )
            )
            member_map = {pid: (role, fav) for pid, role, fav in roles_q.all()}
        else:
            member_map = {}
        return [
            _project_to_response(p, *member_map.get(p.id, (None, False)))
            for p in rows
        ]

    stmt = (
        select(Project, ProjectMember.role, ProjectMember.is_favorite)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.employee_id == principal.employee_id)
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    rows = (await db.execute(stmt.order_by(Project.created_at.desc()))).all()
    return [_project_to_response(p, role, fav) for (p, role, fav) in rows]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    if not can_create_project(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Создание проектов доступно только admin/member ролям в Hub",
        )

    key = body.key
    if key is None:
        try:
            key = await generate_unique_key(
                db, name=body.name, tenant_id=principal.tenant_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Не удалось подобрать уникальный ключ — задайте его вручную",
            ) from exc

    project = Project(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        key=key,
        name=body.name,
        description=body.description,
        created_by=principal.employee_id,
    )
    db.add(project)
    db.add(
        ProjectMember(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            project_id=project.id,
            employee_id=principal.employee_id,
            role="owner",
            added_by=principal.employee_id,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Проект с ключом {key!r} уже существует",
        ) from exc
    await db.refresh(project)
    return _project_to_response(project, my_role="owner")


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, my_role = await require_project_role(db, project_id, principal)
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, my_role or member_role, is_favorite)


@router.put("/projects/{project_id}/favorite", response_model=ProjectResponse)
async def set_favorite(
    project_id: UUID,
    body: ProjectFavoriteUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Личное избранное: любой участник переключает флаг на СВОЁМ членстве."""
    project, _ = await require_project_role(db, project_id, principal)
    member = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == principal.employee_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        # hub:admin вне членства — избранное вешать не на что.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Избранное доступно только участникам проекта",
        )
    member.is_favorite = body.is_favorite
    await db.commit()
    return _project_to_response(project, member.role, member.is_favorite)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, my_role = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project, my_role or "owner")


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    from datetime import UTC, datetime

    project, my_role = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    if project.archived_at is None:
        project.archived_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(project)
    return _project_to_response(project, my_role or "owner")


@router.post("/projects/{project_id}/unarchive", response_model=ProjectResponse)
async def unarchive_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, my_role = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    if project.archived_at is not None:
        project.archived_at = None
        await db.commit()
        await db.refresh(project)
    return _project_to_response(project, my_role or "owner")


# ─── Members ────────────────────────────────────────────────────────────────


async def _list_members(
    db: AsyncSession, project_id: UUID
) -> list[ProjectMemberResponse]:
    """Members + JOIN shadow_users for email/full_name (active rows only)."""
    rows = await db.execute(
        select(
            ProjectMember.id,
            ProjectMember.employee_id,
            ProjectMember.role,
            ProjectMember.added_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == ProjectMember.employee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.added_at)
    )
    return [
        ProjectMemberResponse(
            id=r.id,
            employee_id=r.employee_id,
            role=r.role,
            added_at=r.added_at,
            email=r.email,
            full_name=r.full_name,
        )
        for r in rows.all()
    ]


@router.get(
    "/projects/{project_id}/members", response_model=list[ProjectMemberResponse]
)
async def list_members(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectMemberResponse]:
    await require_project_role(db, project_id, principal)
    return await _list_members(db, project_id)


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: UUID,
    body: ProjectMemberAdd,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))
    # Target employee must exist in shadow_users for this tenant (must have
    # logged into Hub at least once).
    target = await db.get(ShadowUser, body.employee_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сотрудник не найден в Hub. Попросите его сначала зайти на hub.signaris.ru.",
        )
    member = ProjectMember(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        employee_id=body.employee_id,
        role=body.role,
        added_by=principal.employee_id,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот сотрудник уже в проекте",
        ) from exc
    return ProjectMemberResponse(
        id=member.id,
        employee_id=member.employee_id,
        role=member.role,  # type: ignore[arg-type]
        added_at=member.added_at,
        email=target.email,
        full_name=target.full_name,
    )


@router.patch(
    "/projects/{project_id}/members/{member_id}", response_model=ProjectMemberResponse
)
async def update_member(
    project_id: UUID,
    member_id: UUID,
    body: ProjectMemberUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))
    member = await db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")
    # Last-owner protection.
    if member.role == "owner" and body.role != "owner":
        count = await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.role == "owner"
            )
        )
        if len(count.all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="В проекте должен остаться хотя бы один owner",
            )
    member.role = body.role
    await db.commit()
    await db.refresh(member)
    members = await _list_members(db, project_id)
    enriched = next((m for m in members if m.id == member_id), None)
    if enriched is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать участника после обновления",
        )
    return enriched


@router.delete(
    "/projects/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    project_id: UUID,
    member_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_project_role(db, project_id, principal, allow=("owner",))
    member = await db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")
    if member.role == "owner":
        count = await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.role == "owner"
            )
        )
        if len(count.all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="В проекте должен остаться хотя бы один owner",
            )
    await db.delete(member)
    await db.commit()


# Ensure fetch_project_or_404 stays imported (used indirectly via require_project_role).
_ = fetch_project_or_404
