"""Anonymous public-share-token reader (3.6.12).

`GET /api/public/{token}` is the only endpoint in the app served WITHOUT
`require_auth`. Security model:

1. UUID v4 token (122-bit entropy) is the entire capability.
2. Token lookup happens cross-tenant on `public_share_tokens` (no RLS there).
3. ONLY after a valid + active token is found we `bypass_rls=True` to read
   the entity, scoped to the token's tenant_id.
4. Response goes through a sanitizer: no email, no employee_id, no tenant
   info, no attachment download URLs. Names → initials.
5. Returns 404 for both "token not found" and "token revoked/expired" so a
   probe can't tell which one happened (negligible info-leak, but uniform
   responses are simpler to reason about).

Feature-flag (`SIGNARIS_HUB_PUBLIC_LINKS_ENABLED=false`) returns 503 for the
entire surface — kill switch without redeploy.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.attachment import TaskAttachment
from app.models.project import Project
from app.models.section import Section
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskComment
from app.schemas.share import (
    PublicAttachmentMeta,
    PublicComment,
    PublicProjectComment,
    PublicProjectView,
    PublicSection,
    PublicTaskHit,
    PublicTaskView,
)
from app.services.public_token import initials, load_active_token, mask_mentions

router = APIRouter(tags=["public"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка недействительна"
)


@router.get("/public/{token}")
async def get_public(token: UUID) -> PublicTaskView | PublicProjectView:
    settings = get_settings()
    if not settings.public_links_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Публичные ссылки временно отключены",
        )

    # Stage 1 — cross-tenant token lookup (no RLS on public_share_tokens).
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        record = await load_active_token(session, token)
        if record is None:
            raise _NOT_FOUND
        tenant_id = record.tenant_id
        scope = record.scope
        entity_id = record.entity_id

    # Stage 2 — read the entity scoped to the token's tenant.
    async with tenant_scoped_session(tenant_id, bypass_rls=True) as session:
        if scope == "task":
            return await _build_task_view(session, entity_id)
        if scope == "project":
            return await _build_project_view(session, entity_id)
        raise _NOT_FOUND


# ─── Builders ──────────────────────────────────────────────────────────────


async def _initials_for(session: AsyncSession, employee_id: UUID | None) -> str | None:
    if employee_id is None:
        return None
    row = await session.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == employee_id
        )
    )
    rec = row.first()
    if rec is None:
        return None
    return initials(rec.full_name, rec.email)


async def _mention_names(session: AsyncSession) -> dict[str, str]:
    """handle (email local-part, lower) → display name для mask_mentions.

    Tenant-scoped сессия + RLS ограничивают выборку своим tenant'ом.
    """
    rows = await session.execute(
        select(ShadowUser.email, ShadowUser.full_name).limit(500)
    )
    out: dict[str, str] = {}
    for r in rows.all():
        if r.email and r.full_name:
            out[r.email.split("@", 1)[0].lower()] = r.full_name
    return out


async def _build_task_view(session: AsyncSession, task_id: UUID) -> PublicTaskView:
    task = await session.get(Task, task_id)
    if task is None or task.archived_at is not None:
        raise _NOT_FOUND

    assignee_init = await _initials_for(session, task.assignee_id)
    creator_init = await _initials_for(session, task.created_by)

    comment_rows = await session.execute(
        select(
            TaskComment.body,
            TaskComment.created_at,
            ShadowUser.full_name,
            ShadowUser.email,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskComment.author_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(
            TaskComment.task_id == task_id,
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at)
    )
    mention_names = await _mention_names(session)
    comments = [
        PublicComment(
            author_initials=initials(r.full_name, r.email),
            body=mask_mentions(r.body, mention_names),
            created_at=r.created_at,
        )
        for r in comment_rows.all()
    ]

    attachment_rows = await session.execute(
        select(
            TaskAttachment.filename,
            TaskAttachment.size_bytes,
            TaskAttachment.mime,
        ).where(TaskAttachment.task_id == task_id)
    )
    attachments = [
        PublicAttachmentMeta(filename=r.filename, size_bytes=r.size_bytes, mime=r.mime)
        for r in attachment_rows.all()
    ]

    return PublicTaskView(
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        start_at=task.start_at,
        due_at=task.due_at,
        assignee_initials=assignee_init,
        created_by_initials=creator_init,
        created_at=task.created_at,
        comments=comments,
        attachments=attachments,
    )


async def _build_project_view(
    session: AsyncSession, project_id: UUID
) -> PublicProjectView:
    project = await session.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise _NOT_FOUND

    section_rows = (
        await session.execute(
            select(Section)
            .where(Section.project_id == project_id)
            .order_by(Section.position)
        )
    ).scalars().all()

    task_rows = await session.execute(
        select(
            Task.id,
            Task.title,
            Task.status,
            Task.priority,
            Task.due_at,
            Task.section_id,
            Task.assignee_id,
            Task.parent_task_id,
        )
        .where(Task.project_id == project_id, Task.archived_at.is_(None))
        .order_by(Task.position)
    )
    tasks_by_section: dict[UUID | None, list[tuple]] = {}
    assignee_ids: set[UUID] = set()
    for row in task_rows.all():
        tasks_by_section.setdefault(row.section_id, []).append(row)
        if row.assignee_id is not None:
            assignee_ids.add(row.assignee_id)

    # Pre-fetch attachment counts in one query — avoids N+1 on large boards.
    has_att_rows = await session.execute(
        select(TaskAttachment.task_id).distinct()
    )
    has_attachments_set = {row[0] for row in has_att_rows.all()}

    # Pre-fetch assignee initials in one query — avoids N+1 per task.
    initials_by_id: dict[UUID, str | None] = {}
    if assignee_ids:
        au_rows = await session.execute(
            select(
                ShadowUser.employee_id,
                ShadowUser.full_name,
                ShadowUser.email,
            ).where(ShadowUser.employee_id.in_(assignee_ids))
        )
        for au in au_rows.all():
            initials_by_id[au.employee_id] = initials(au.full_name, au.email)

    def _row_to_hit(row) -> PublicTaskHit:  # noqa: ANN001 — local helper
        return PublicTaskHit(
            id=row.id,
            title=row.title,
            status=row.status,
            priority=row.priority,
            due_at=row.due_at,
            assignee_initials=(
                initials_by_id.get(row.assignee_id)
                if row.assignee_id is not None
                else None
            ),
            has_attachments=row.id in has_attachments_set,
            is_subtask=row.parent_task_id is not None,
        )

    sections: list[PublicSection] = []
    # "Без секции" bucket first.
    orphan = tasks_by_section.get(None, [])
    if orphan:
        sections.append(
            PublicSection(
                id=project.id,  # synthetic — UI uses project.id as anchor
                name="Без секции",
                tasks=[_row_to_hit(r) for r in orphan],
            )
        )
    for section in section_rows:
        rows = tasks_by_section.get(section.id, [])
        sections.append(
            PublicSection(
                id=section.id,
                name=section.name,
                tasks=[_row_to_hit(r) for r in rows],
            )
        )

    # Top-10 most recent comments across every visible task — gives a public
    # viewer a quick "what's the team talking about?" without revealing names.
    recent_comment_rows = await session.execute(
        select(
            TaskComment.body,
            TaskComment.created_at,
            Task.title,
            ShadowUser.full_name,
            ShadowUser.email,
        )
        .join(Task, Task.id == TaskComment.task_id)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskComment.author_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at.desc())
        .limit(10)
    )
    mention_names = await _mention_names(session)
    recent_comments = [
        PublicProjectComment(
            task_title=r.title,
            author_initials=initials(r.full_name, r.email),
            body=mask_mentions(r.body, mention_names),
            created_at=r.created_at,
        )
        for r in recent_comment_rows.all()
    ]

    return PublicProjectView(
        name=project.name,
        description=project.description,
        sections=sections,
        recent_comments=recent_comments,
    )
