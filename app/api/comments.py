"""Task comments API.

Auto-watch behavior: posting a comment makes the author a watcher of the task
(reason `manual`); упомянутые подписываются с reason `mentioned`.

**Упоминание ВЫДАЁТ viewer-членство в проекте** (решение владельца 14.09) —
зеркало ручки наблюдателей (`app/api/watchers.py`): подписка без доступа вела
бы в 404, а с 14.09 упомянуть можно любого сотрудника по имени, не зная его
логина. Членство идемпотентно и НЕ отзывается, если упоминание убрали из
текста, — ровно как у наблюдателей и исполнителей. В личном проекте это
безопасно: `personal_task_scope` покажет приглашённому только ту задачу, где
он исполнитель или наблюдатель, а не весь личный список.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskComment, TaskWatcher  # noqa: F401 — used below
from app.schemas.comment import CommentCreate, CommentResponse, CommentUpdate
from app.services.activity_writer import record_activity
from app.services.mention_parser import (
    mention_names,
    render_mentions,
    resolve_mentions,
)
from app.services.notify import notify_commented, notify_mentioned
from app.services.personal_projects import require_task_access
from app.services.project_access import ensure_project_member

router = APIRouter(tags=["comments"])


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal)
    return task


async def _ensure_watcher(
    db: AsyncSession, *, task_id: UUID, tenant_id: UUID, employee_id: UUID, reason: str
) -> None:
    """Idempotent watcher insert — ON CONFLICT DO NOTHING."""
    await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task_id,
            employee_id=employee_id,
            tenant_id=tenant_id,
            added_reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )


async def _subscribe_mentioned(
    db: AsyncSession,
    *,
    task_id: UUID,
    project_id: UUID,
    tenant_id: UUID,
    mentioned_ids: list[UUID],
    actor_id: UUID,
) -> None:
    """Упомянутый становится наблюдателем И участником проекта.

    Членство обязательно: иначе пуш «вас упомянули» ведёт на карточку, которую
    человек не видит (404). Зеркало `app/api/watchers.py::add_watcher`.
    """
    for emp_id in mentioned_ids:
        if emp_id == actor_id:
            continue
        await _ensure_watcher(
            db,
            task_id=task_id,
            tenant_id=tenant_id,
            employee_id=emp_id,
            reason="mentioned",
        )
        await ensure_project_member(
            db,
            project_id=project_id,
            tenant_id=tenant_id,
            employee_id=emp_id,
            added_by=actor_id,
        )


async def _list_with_authors(
    db: AsyncSession, task_id: UUID, tenant_id: UUID
) -> list[CommentResponse]:
    rows = await db.execute(
        select(
            TaskComment.id,
            TaskComment.task_id,
            TaskComment.author_id,
            TaskComment.body,
            TaskComment.mentioned_ids,
            TaskComment.edited_at,
            TaskComment.created_at,
            ShadowUser.email,
            ShadowUser.full_name,
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
    comments = rows.all()
    # Словарь «токен → ФИО» одним запросом на ВЕСЬ список. Раньше его строил
    # клиент из `/tenant/members` с лимитом 10, и имя вместо логина видели
    # только первые десять сотрудников по алфавиту.
    names = await mention_names(
        db, texts=[r.body for r in comments], tenant_id=tenant_id
    )
    return [
        CommentResponse(
            id=r.id,
            task_id=r.task_id,
            author_id=r.author_id,
            body=r.body,
            mentioned_ids=list(r.mentioned_ids or []),
            edited_at=r.edited_at,
            created_at=r.created_at,
            author_email=r.email,
            author_full_name=r.full_name,
            mention_names=names,
        )
        for r in comments
    ]


@router.get("/tasks/{task_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CommentResponse]:
    task = await _fetch_task_visible(db, task_id, principal)
    return await _list_with_authors(db, task_id, task.tenant_id)


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    task_id: UUID,
    body: CommentCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    await enforce_rate_limit(
        bucket="comment:write",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    task = await _fetch_task_visible(db, task_id, principal)

    mentioned_ids = await resolve_mentions(
        db, text=body.body, tenant_id=task.tenant_id
    )

    comment = TaskComment(
        id=uuid4(),
        tenant_id=task.tenant_id,
        task_id=task.id,
        author_id=principal.employee_id,
        body=body.body,
        mentioned_ids=mentioned_ids,
    )
    db.add(comment)
    await db.flush()  # need comment.id before activity row references it indirectly

    await _ensure_watcher(
        db,
        task_id=task.id,
        tenant_id=task.tenant_id,
        employee_id=principal.employee_id,
        reason="manual",
    )
    # Упомянутые подписываются и получают доступ к проекту (см. докстринг).
    await _subscribe_mentioned(
        db,
        task_id=task.id,
        project_id=task.project_id,
        tenant_id=task.tenant_id,
        mentioned_ids=mentioned_ids,
        actor_id=principal.employee_id,
    )
    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="commented",
        payload={
            "comment_id": str(comment.id),
            "mentioned_ids": [str(i) for i in mentioned_ids],
        },
    )

    # Notifications: mentioned juniors first, then remaining watchers.
    # Skip self. `mentioned` takes precedence over `commented` for the same
    # recipient (so you don't get two notifications for the same comment).
    actor_row = await db.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == principal.employee_id
        )
    )
    actor = actor_row.first()
    actor_name = (actor.full_name if actor else None) or (
        actor.email if actor else "Кто-то"
    )
    # В тексте уведомления вместо токена должно стоять имя: «@Иван_Петров»
    # в пуше читается как ошибка.
    names = await mention_names(db, texts=[body.body], tenant_id=task.tenant_id)
    shown_body = render_mentions(body.body, names)
    notified: set[UUID] = {principal.employee_id}
    for emp_id in mentioned_ids:
        if emp_id in notified:
            continue
        await notify_mentioned(
            db,
            task=task,
            comment_body=shown_body,
            actor_name=actor_name,
            recipient_id=emp_id,
        )
        notified.add(emp_id)
    watcher_rows = await db.execute(
        select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
    )
    for (emp_id,) in watcher_rows.all():
        if emp_id in notified:
            continue
        await notify_commented(
            db,
            task=task,
            comment_body=shown_body,
            actor_name=actor_name,
            recipient_id=emp_id,
        )
        notified.add(emp_id)

    await db.commit()
    await db.refresh(comment)
    # Re-fetch with author JOIN.
    out = await _list_with_authors(db, task_id, task.tenant_id)
    matching = next((c for c in out if c.id == comment.id), None)
    if matching is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать комментарий",
        )
    return matching


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: UUID,
    body: CommentUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    comment = await db.get(TaskComment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    if comment.author_id != principal.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Редактировать может только автор",
        )
    comment.body = body.body
    comment.edited_at = datetime.now(UTC)
    # Re-parse mentions: someone may have been @added on edit. Auto-watch
    # the new mentions (we don't unwatch the old ones — that's nicer UX).
    new_mentions = await resolve_mentions(
        db, text=body.body, tenant_id=comment.tenant_id
    )
    comment.mentioned_ids = new_mentions
    task = await db.get(Task, comment.task_id)
    if task is not None:
        await _subscribe_mentioned(
            db,
            task_id=comment.task_id,
            project_id=task.project_id,
            tenant_id=comment.tenant_id,
            mentioned_ids=new_mentions,
            actor_id=principal.employee_id,
        )
    await db.commit()
    out = await _list_with_authors(db, comment.task_id, comment.tenant_id)
    matching = next((c for c in out if c.id == comment.id), None)
    if matching is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать комментарий",
        )
    return matching


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    comment = await db.get(TaskComment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    if comment.author_id != principal.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Удалять может только автор",
        )
    comment.deleted_at = datetime.now(UTC)
    await db.commit()
