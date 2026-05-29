"""Share-token management API — create / list / revoke (3.6.12).

Authenticated endpoints for project owners/editors to mint public links.
The anonymous read path lives in `app/api/public.py`.

Permissions:
- POST `/api/projects/{id}/share`     — owner/editor on project
- POST `/api/tasks/{id}/share`        — owner/editor on the task's project
- GET  `/api/projects/{id}/shares`    — viewer+
- GET  `/api/tasks/{id}/shares`       — viewer+
- DELETE `/api/share/{token}`         — creator OR project owner / hub:admin

A 404 on /api/public/{token} hides whether the entity exists; only the
authenticated owner can see/revoke the token list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_db, require_auth
from app.models.share import PublicShareToken
from app.models.task import Task
from app.schemas.share import ShareCreate, ShareResponse
from app.services.project_access import is_hub_admin, require_project_role

router = APIRouter(tags=["share"])


def _disabled_if_off() -> None:
    if not get_settings().public_links_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Публичные ссылки временно отключены",
        )


def _build_url(token: UUID) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/p/{token}"


def _to_response(row: PublicShareToken) -> ShareResponse:
    return ShareResponse(
        id=row.id,
        scope=row.scope,  # type: ignore[arg-type]
        entity_id=row.entity_id,
        token=row.token,
        url=_build_url(row.token),
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


# ─── Create ────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/share",
    response_model=ShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_share(
    project_id: UUID,
    body: ShareCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ShareResponse:
    _disabled_if_off()
    await require_project_role(
        db, project_id, principal, allow=("owner", "editor")
    )
    record = PublicShareToken(
        tenant_id=principal.tenant_id,
        scope="project",
        entity_id=project_id,
        created_by=principal.employee_id,
        expires_at=body.expires_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _to_response(record)


@router.post(
    "/tasks/{task_id}/share",
    response_model=ShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_share(
    task_id: UUID,
    body: ShareCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ShareResponse:
    _disabled_if_off()
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
    )
    record = PublicShareToken(
        tenant_id=principal.tenant_id,
        scope="task",
        entity_id=task.id,
        created_by=principal.employee_id,
        expires_at=body.expires_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _to_response(record)


# ─── List ──────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/shares",
    response_model=list[ShareResponse],
)
async def list_project_shares(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ShareResponse]:
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(PublicShareToken)
        .where(
            PublicShareToken.scope == "project",
            PublicShareToken.entity_id == project_id,
            PublicShareToken.revoked_at.is_(None),
        )
        .order_by(PublicShareToken.created_at.desc())
    )
    return [_to_response(r) for r in rows.scalars().all()]


@router.get("/tasks/{task_id}/shares", response_model=list[ShareResponse])
async def list_task_shares(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ShareResponse]:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(db, task.project_id, principal)
    rows = await db.execute(
        select(PublicShareToken)
        .where(
            PublicShareToken.scope == "task",
            PublicShareToken.entity_id == task.id,
            PublicShareToken.revoked_at.is_(None),
        )
        .order_by(PublicShareToken.created_at.desc())
    )
    return [_to_response(r) for r in rows.scalars().all()]


# ─── Revoke ────────────────────────────────────────────────────────────────


@router.delete("/share/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    token: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    record = (
        await db.execute(
            select(PublicShareToken).where(PublicShareToken.token == token)
        )
    ).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        # Idempotent — already revoked / never existed → no-op 204.
        return

    # creator OR project-owner OR hub:admin can revoke.
    if record.created_by != principal.employee_id and not is_hub_admin(principal):
        # Need owner-role on the associated project. For task-scope:
        # fetch the task to find project_id.
        project_id: UUID
        if record.scope == "project":
            project_id = record.entity_id
        else:
            task = await db.get(Task, record.entity_id)
            if task is None:
                # Stale token → nothing to revoke from.
                return
            project_id = task.project_id
        await require_project_role(db, project_id, principal, allow=("owner",))

    record.revoked_at = datetime.now(UTC)
    await db.commit()
