"""GET /api/search?q=... — basic ILIKE search across projects + tasks.

Light implementation for Hub-MVP.3a sidebar quick-search: returns up to 10
projects and 10 task matches in the current tenant. Full-text search with
filters/ranking lands in Phase 3.6.6 (see docs/products/HUB.md).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.models.project import Project, ProjectMember
from app.models.task import Task
from app.services.project_access import is_hub_admin

router = APIRouter(tags=["search"])


class SearchHit(BaseModel):
    kind: Literal["project", "task"]
    id: UUID
    title: str
    subtitle: str | None = None
    project_id: UUID | None = None


class SearchResponse(BaseModel):
    projects: list[SearchHit]
    tasks: list[SearchHit]


def _ilike(s: str) -> str:
    # Escape % and _ to keep the query literal-ish.
    return "%" + s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2, max_length=128),
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    pattern = _ilike(q)

    # Projects — hub:admin sees the whole tenant; others — only their memberships.
    project_stmt = select(Project).where(
        Project.archived_at.is_(None), Project.name.ilike(pattern)
    )
    if not is_hub_admin(principal):
        project_stmt = project_stmt.join(
            ProjectMember, ProjectMember.project_id == Project.id
        ).where(ProjectMember.employee_id == principal.employee_id)
    project_rows = (await db.execute(project_stmt.limit(10))).scalars().all()

    # Tasks — only inside visible projects (subquery via ProjectMember unless admin).
    task_stmt = (
        select(Task, Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(Task.title.ilike(pattern), Task.archived_at.is_(None))
        .order_by(Task.updated_at.desc())
    )
    if not is_hub_admin(principal):
        task_stmt = task_stmt.join(
            ProjectMember, ProjectMember.project_id == Task.project_id
        ).where(ProjectMember.employee_id == principal.employee_id)
    task_rows = (await db.execute(task_stmt.limit(10))).all()

    return SearchResponse(
        projects=[
            SearchHit(
                kind="project",
                id=p.id,
                title=p.name,
                subtitle=p.key,
            )
            for p in project_rows
        ],
        tasks=[
            SearchHit(
                kind="task",
                id=t.id,
                title=t.title,
                subtitle=project_name,
                project_id=t.project_id,
            )
            for (t, project_name) in task_rows
        ],
    )
