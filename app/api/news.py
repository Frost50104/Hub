"""Новости API (Ф2, ТЗ §12): лента, реакции, комментарии, ознакомления.

Permissions: чтение — published + audience; author — свои черновики,
publisher/admin — всё; публикация — publisher+. На публикацию — батч-рассылка
news.published (или news.ack_required, если требуется ознакомление).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.audience import AudienceMember
from app.models.employee_profile import EmployeeProfile
from app.models.engagement import Favorite
from app.models.news import (
    REACTION_EMOJIS,
    NewsAcknowledgement,
    NewsComment,
    NewsPost,
    NewsReaction,
)
from app.models.shadow import ShadowUser
from app.schemas.library import AudienceBody
from app.schemas.news import (
    CommentCreate,
    CommentResponse,
    NewsCreate,
    NewsListResponse,
    NewsResponse,
    NewsUpdate,
    ReactionBody,
)
from app.services import audit, lifecycle
from app.services.audience_resolver import RuleSpec, set_object_audience, visible_filter
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_notify import _employee_ids
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile
from app.services.rich_content import (
    NEWS_NODES,
    RichContentError,
    extract_text,
    validate_rich_content,
)
from app.services.search_indexer import delete_document, upsert_document

router = APIRouter(tags=["learn-news"])

_OBJECT_TYPE = "news_post"


def _rule_specs(body: AudienceBody) -> list[RuleSpec]:
    return [
        RuleSpec(
            mode=r.mode,
            profile_ids=frozenset(r.profile_ids),
            position_ids=frozenset(r.position_ids),
            position_group_ids=frozenset(r.position_group_ids),
            store_ids=frozenset(r.store_ids),
            store_group_ids=frozenset(r.store_group_ids),
            franchisee_ids=frozenset(r.franchisee_ids),
            franchisee_group_ids=frozenset(r.franchisee_group_ids),
            department_ids=frozenset(r.department_ids),
            user_group_ids=frozenset(r.user_group_ids),
        )
        for r in body.rules
    ]


def _validate_body(payload: dict) -> dict:
    try:
        return validate_rich_content(payload, allowed_nodes=NEWS_NODES)
    except RichContentError as e:
        raise HTTPException(status_code=422, detail=f"Содержимое: {e}") from None


async def _get_post_or_404(db: AsyncSession, post_id: UUID) -> NewsPost:
    post = await db.get(NewsPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Новость не найдена")
    return post


def _require_manage(
    post: NewsPost, principal: Principal, role: lifecycle.ContentRole
) -> None:
    if lifecycle.can(role, "publisher"):
        return
    if role == "author" and post.created_by == principal.employee_id:
        return
    raise HTTPException(status_code=403, detail="Это не ваша новость")


async def _post_visible_to(
    db: AsyncSession,
    post: NewsPost,
    principal: Principal,
    role: lifecycle.ContentRole,
    profile_id: UUID | None,
) -> bool:
    if lifecycle.can(role, "publisher"):
        return True
    if role == "author" and post.created_by == principal.employee_id:
        return True
    if post.status != "published":
        return False
    if post.audience_id is None:
        return True
    if profile_id is None:
        return False
    row = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.audience_id == post.audience_id,
            AudienceMember.profile_id == profile_id,
        )
    )
    return row.scalar_one_or_none() is not None


async def _reindex(db: AsyncSession, post: NewsPost) -> None:
    if post.status == "published":
        await upsert_document(
            db,
            tenant_id=post.tenant_id,
            object_type=_OBJECT_TYPE,
            object_id=post.id,
            title=post.title,
            body_text=extract_text(post.body),
            audience_id=post.audience_id,
            published_at=post.published_at,
            url_path=f"/learn/news?p={post.id}",
        )
    else:
        await delete_document(db, object_type=_OBJECT_TYPE, object_id=post.id)


async def _audience_profile_ids(db: AsyncSession, audience_id: UUID | None) -> list[UUID]:
    if audience_id is None:
        rows = await db.execute(
            select(EmployeeProfile.id).where(EmployeeProfile.status == "active")
        )
    else:
        rows = await db.execute(
            select(AudienceMember.profile_id).where(AudienceMember.audience_id == audience_id)
        )
    return [r[0] for r in rows]


# --- Лента -------------------------------------------------------------------


@router.get("/learn/news", response_model=NewsListResponse)
async def list_news(
    manage: bool = Query(default=False),
    limit: int = Query(default=20, le=50),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsListResponse:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None

    if manage and lifecycle.can(role, "publisher"):
        stmt = select(NewsPost)
    elif manage and role == "author":
        stmt = select(NewsPost).where(
            (NewsPost.created_by == principal.employee_id)
            | (
                (NewsPost.status == "published")
                & visible_filter(NewsPost, profile_id or UUID(int=0))
            )
        )
    else:
        stmt = select(NewsPost).where(
            NewsPost.status == "published",
            visible_filter(NewsPost, profile_id or UUID(int=0)),
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    now = datetime.now(UTC)
    posts = list(
        (
            await db.execute(
                stmt.order_by(
                    # Закреплённые (pinned_until в будущем) — сверху.
                    (
                        func.coalesce(
                            NewsPost.pinned_until, datetime(1970, 1, 1, tzinfo=UTC)
                        )
                        > now
                    ).desc(),
                    func.coalesce(NewsPost.published_at, NewsPost.created_at).desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    post_ids = [p.id for p in posts]

    reactions: dict[UUID, dict[str, int]] = {}
    my_reactions: dict[UUID, list[str]] = {}
    comments_count: dict[UUID, int] = {}
    acked: set[UUID] = set()
    favorites: set[UUID] = set()
    if post_ids:
        for post_id, emoji, count in await db.execute(
            select(NewsReaction.post_id, NewsReaction.emoji, func.count())
            .where(NewsReaction.post_id.in_(post_ids))
            .group_by(NewsReaction.post_id, NewsReaction.emoji)
        ):
            reactions.setdefault(post_id, {})[emoji] = count
        if profile_id:
            for post_id, emoji in await db.execute(
                select(NewsReaction.post_id, NewsReaction.emoji).where(
                    NewsReaction.post_id.in_(post_ids),
                    NewsReaction.profile_id == profile_id,
                )
            ):
                my_reactions.setdefault(post_id, []).append(emoji)
            acked = {
                r[0]
                for r in await db.execute(
                    select(NewsAcknowledgement.post_id).where(
                        NewsAcknowledgement.post_id.in_(post_ids),
                        NewsAcknowledgement.profile_id == profile_id,
                    )
                )
            }
            favorites = {
                r[0]
                for r in await db.execute(
                    select(Favorite.object_id).where(
                        Favorite.profile_id == profile_id,
                        Favorite.object_type == _OBJECT_TYPE,
                        Favorite.object_id.in_(post_ids),
                    )
                )
            }
        for post_id, count in await db.execute(
            select(NewsComment.post_id, func.count())
            .where(NewsComment.post_id.in_(post_ids), NewsComment.deleted_at.is_(None))
            .group_by(NewsComment.post_id)
        ):
            comments_count[post_id] = count

    author_ids = {p.created_by for p in posts if p.created_by}
    authors: dict[UUID, str] = {}
    if author_ids:
        authors = {
            r[0]: r[1]
            for r in await db.execute(
                select(ShadowUser.employee_id, ShadowUser.full_name).where(
                    ShadowUser.employee_id.in_(author_ids)
                )
            )
        }

    items = []
    for p in posts:
        resp = NewsResponse.model_validate(p)
        resp.author_name = authors.get(p.created_by) if p.created_by else None
        resp.reactions = reactions.get(p.id, {})
        resp.my_reactions = my_reactions.get(p.id, [])
        resp.comments_count = comments_count.get(p.id, 0)
        resp.acked_by_me = p.id in acked
        resp.ack_pending = (
            p.requires_acknowledgement and p.status == "published" and p.id not in acked
        )
        resp.is_favorite = p.id in favorites
        items.append(resp)
    return NewsListResponse(items=items, total=total, content_role=role)


# --- CRUD --------------------------------------------------------------------


@router.post("/learn/news", response_model=NewsResponse, status_code=201)
async def create_news(
    body: NewsCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    await require_content_role(db, principal, "author")
    post = NewsPost(
        tenant_id=principal.tenant_id,
        title=body.title,
        body=_validate_body(body.body),
        allow_comments=body.allow_comments,
        allow_reactions=body.allow_reactions,
        requires_acknowledgement=body.requires_acknowledgement,
        owner_id=principal.employee_id,
        created_by=principal.employee_id,
    )
    db.add(post)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=_OBJECT_TYPE,
        object_id=post.id,
        object_label=post.title,
    )
    await db.commit()
    await db.refresh(post)
    return NewsResponse.model_validate(post)


@router.patch("/learn/news/{post_id}", response_model=NewsResponse)
async def update_news(
    post_id: UUID,
    body: NewsUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    role = await require_content_role(db, principal, "author")
    post = await _get_post_or_404(db, post_id)
    _require_manage(post, principal, role)
    fields = body.model_dump(exclude_unset=True)
    if "body" in fields:
        fields["body"] = _validate_body(fields["body"])
    for name, value in fields.items():
        setattr(post, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=post.id,
        object_label=post.title,
    )
    await _reindex(db, post)
    await db.commit()
    await db.refresh(post)
    return NewsResponse.model_validate(post)


@router.delete("/learn/news/{post_id}", status_code=204)
async def delete_news(
    post_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    post = await _get_post_or_404(db, post_id)
    _require_manage(post, principal, role)
    if post.published_at is not None:
        raise HTTPException(
            status_code=409, detail="Новость публиковалась — используйте архив"
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=_OBJECT_TYPE,
        object_id=post.id,
        object_label=post.title,
    )
    await delete_document(db, object_type=_OBJECT_TYPE, object_id=post.id)
    await db.delete(post)
    await db.commit()


@router.post("/learn/news/{post_id}/status", response_model=NewsResponse)
async def change_news_status(
    post_id: UUID,
    body: dict,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    new_status = body.get("status")
    if new_status not in ("draft", "review", "published", "archived"):
        raise HTTPException(status_code=422, detail="Некорректный статус")
    role = await require_content_role(db, principal, "author")
    post = await _get_post_or_404(db, post_id)
    _require_manage(post, principal, role)

    was_published = post.status == "published"
    lifecycle.transition(
        db,
        post,
        new_status,
        actor_id=principal.employee_id,
        role=role,
        tenant_id=principal.tenant_id,
        object_type=_OBJECT_TYPE,
        object_label=post.title,
    )
    await _reindex(db, post)

    if post.status == "published" and not was_published:
        profile_ids = await _audience_profile_ids(db, post.audience_id)
        recipients = await _employee_ids(db, profile_ids)
        kind = "news.ack_required" if post.requires_acknowledgement else "news.published"
        await notify_many(
            db,
            tenant_id=post.tenant_id,
            employee_ids=list(recipients.values()),
            kind=kind,
            title=post.title,
            body=(
                "Новость требует ознакомления."
                if post.requires_acknowledgement
                else "Новая новость компании."
            ),
            url=f"/learn/news?p={post.id}",
            payload={"post_id": str(post.id)},
        )
    await db.commit()
    await db.refresh(post)
    return NewsResponse.model_validate(post)


@router.put("/learn/news/{post_id}/audience", response_model=NewsResponse)
async def set_news_audience(
    post_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    await require_content_role(db, principal, "publisher")
    post = await _get_post_or_404(db, post_id)
    try:
        audience_id, _diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=post.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"{_OBJECT_TYPE}:{post.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    post.audience_id = audience_id
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=_OBJECT_TYPE,
        object_id=post.id,
        object_label=post.title,
    )
    await _reindex(db, post)
    await db.commit()
    await db.refresh(post)
    return NewsResponse.model_validate(post)


# --- Реакции / ack / комментарии --------------------------------------------


@router.post("/learn/news/{post_id}/reactions", response_model=NewsResponse)
async def toggle_reaction(
    post_id: UUID,
    body: ReactionBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    if body.emoji not in REACTION_EMOJIS:
        raise HTTPException(status_code=422, detail="Недопустимая реакция")
    role = await resolve_content_role(db, principal)
    post = await _get_post_or_404(db, post_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _post_visible_to(db, post, principal, role, profile.id):
        raise HTTPException(status_code=404, detail="Новость не найдена")
    if not post.allow_reactions:
        raise HTTPException(status_code=422, detail="Реакции отключены")

    existing = (
        await db.execute(
            select(NewsReaction).where(
                NewsReaction.post_id == post_id,
                NewsReaction.profile_id == profile.id,
                NewsReaction.emoji == body.emoji,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
    else:
        db.add(
            NewsReaction(
                tenant_id=post.tenant_id,
                post_id=post_id,
                profile_id=profile.id,
                emoji=body.emoji,
            )
        )
    await db.commit()
    await db.refresh(post)
    return NewsResponse.model_validate(post)


@router.post("/learn/news/{post_id}/ack", status_code=204)
async def acknowledge_news(
    post_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await resolve_content_role(db, principal)
    post = await _get_post_or_404(db, post_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _post_visible_to(db, post, principal, role, profile.id):
        raise HTTPException(status_code=404, detail="Новость не найдена")
    if not post.requires_acknowledgement or post.status != "published":
        raise HTTPException(status_code=422, detail="Новость не требует ознакомления")
    stmt = pg_insert(NewsAcknowledgement).values(
        post_id=post_id, profile_id=profile.id, tenant_id=post.tenant_id
    )
    await db.execute(stmt.on_conflict_do_nothing(index_elements=["post_id", "profile_id"]))
    await db.commit()


@router.get("/learn/news/{post_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    post_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CommentResponse]:
    role = await resolve_content_role(db, principal)
    post = await _get_post_or_404(db, post_id)
    profile = await get_profile(db, principal)
    if not await _post_visible_to(db, post, principal, role, profile.id if profile else None):
        raise HTTPException(status_code=404, detail="Новость не найдена")
    rows = await db.execute(
        select(NewsComment, ShadowUser.full_name)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == NewsComment.author_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(NewsComment.post_id == post_id)
        .order_by(NewsComment.created_at)
    )
    out = []
    for comment, author_name in rows:
        out.append(
            CommentResponse(
                id=comment.id,
                author_id=comment.author_id,
                author_name=author_name,
                body="" if comment.deleted_at else comment.body,
                edited_at=comment.edited_at,
                deleted_at=comment.deleted_at,
                created_at=comment.created_at,
            )
        )
    return out


@router.post(
    "/learn/news/{post_id}/comments", response_model=CommentResponse, status_code=201
)
async def create_comment(
    post_id: UUID,
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
    role = await resolve_content_role(db, principal)
    post = await _get_post_or_404(db, post_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _post_visible_to(db, post, principal, role, profile.id):
        raise HTTPException(status_code=404, detail="Новость не найдена")
    if not post.allow_comments:
        raise HTTPException(status_code=422, detail="Комментарии отключены")
    comment = NewsComment(
        tenant_id=post.tenant_id,
        post_id=post_id,
        author_id=principal.employee_id,
        body=body.body,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return CommentResponse(
        id=comment.id,
        author_id=comment.author_id,
        author_name=principal.full_name,
        body=comment.body,
        edited_at=None,
        deleted_at=None,
        created_at=comment.created_at,
    )


@router.delete("/learn/news/{post_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    post_id: UUID,
    comment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await resolve_content_role(db, principal)
    comment = await db.get(NewsComment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    if comment.author_id != principal.employee_id and not lifecycle.can(role, "publisher"):
        raise HTTPException(status_code=403, detail="Можно удалять только свои комментарии")
    comment.deleted_at = datetime.now(UTC)
    await db.commit()
