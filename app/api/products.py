"""Ассортимент API (Ф4, ТЗ §9): категории, карточки, связи с обучением.

Паттерн доступа — как библиотека: потребитель видит published-карточки
своей аудитории; author правит свои, publisher/admin — все. Первое
открытие карточки → activity-событие product.first_view.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.audience import AudienceMember
from app.models.course import Course, CourseLesson
from app.models.library import LibraryMaterial, ViewHistory
from app.models.product import ProductCard, ProductCardLink, ProductCategory
from app.schemas.library import AudienceBody, StatusBody
from app.schemas.product import (
    CategoryBody,
    CategoryResponse,
    ProductLinkResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpsert,
)
from app.services import audit, lifecycle
from app.services.audience_resolver import RuleSpec, set_object_audience, visible_filter
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_media import sign_media_path
from app.services.org_scope import get_profile
from app.services.points import award
from app.services.search_indexer import delete_document, upsert_document

router = APIRouter(tags=["learn-products"])

_OBJECT_TYPE = "product"


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


async def _get_card_or_404(db: AsyncSession, product_id: UUID) -> ProductCard:
    card = await db.get(ProductCard, product_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    return card


def _require_manage(
    card: ProductCard, principal: Principal, role: lifecycle.ContentRole
) -> None:
    if lifecycle.can(role, "publisher"):
        return
    if role == "author" and card.created_by == principal.employee_id:
        return
    raise HTTPException(status_code=403, detail="Это не ваша карточка")


async def _card_visible_to(
    db: AsyncSession,
    card: ProductCard,
    principal: Principal,
    role: lifecycle.ContentRole,
    profile_id: UUID | None,
) -> bool:
    if lifecycle.can(role, "publisher"):
        return True
    if role == "author" and card.created_by == principal.employee_id:
        return True
    if card.status != "published":
        return False
    if card.audience_id is None:
        return True
    if profile_id is None:
        return False
    member = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.audience_id == card.audience_id,
            AudienceMember.profile_id == profile_id,
        )
    )
    return member.scalar_one_or_none() is not None


async def _reindex(db: AsyncSession, card: ProductCard) -> None:
    if card.status == "published":
        await upsert_document(
            db,
            tenant_id=card.tenant_id,
            object_type=_OBJECT_TYPE,
            object_id=card.id,
            title=card.title,
            snippet=card.description,
            body_text=" ".join(
                filter(None, [card.composition, card.serving, card.upsell])
            )
            or None,
            audience_id=card.audience_id,
            published_at=card.published_at,
            url_path=f"/learn/products?p={card.id}",
        )
    else:
        await delete_document(db, object_type=_OBJECT_TYPE, object_id=card.id)


async def _resolve_links(
    db: AsyncSession, product_ids: list[UUID]
) -> dict[UUID, list[ProductLinkResponse]]:
    """Ссылки «изучить по теме» с названиями и путями (мёртвые скрываются)."""
    if not product_ids:
        return {}
    links = (
        (
            await db.execute(
                select(ProductCardLink)
                .where(ProductCardLink.product_id.in_(product_ids))
                .order_by(ProductCardLink.position)
            )
        )
        .scalars()
        .all()
    )
    by_type: dict[str, set[UUID]] = {}
    for link in links:
        by_type.setdefault(link.object_type, set()).add(link.object_id)

    titles: dict[tuple[str, UUID], tuple[str, str]] = {}
    if by_type.get("course"):
        for cid, title in await db.execute(
            select(Course.id, Course.title).where(Course.id.in_(by_type["course"]))
        ):
            titles[("course", cid)] = (title, f"/learn/courses/{cid}")
    if by_type.get("lesson"):
        for lid, title in await db.execute(
            select(CourseLesson.id, CourseLesson.title).where(
                CourseLesson.id.in_(by_type["lesson"])
            )
        ):
            titles[("lesson", lid)] = (title, f"/learn/lessons/{lid}")
    if by_type.get("material"):
        for mid, title in await db.execute(
            select(LibraryMaterial.id, LibraryMaterial.title).where(
                LibraryMaterial.id.in_(by_type["material"])
            )
        ):
            titles[("material", mid)] = (title, f"/learn/library?m={mid}")

    out: dict[UUID, list[ProductLinkResponse]] = {}
    for link in links:
        resolved = titles.get((link.object_type, link.object_id))
        if resolved is None:
            continue  # объект удалён — ссылку не показываем
        out.setdefault(link.product_id, []).append(
            ProductLinkResponse(
                object_type=link.object_type,
                object_id=link.object_id,
                title=resolved[0],
                url_path=resolved[1],
            )
        )
    return out


def _photo_urls(card: ProductCard) -> list[str]:
    urls = []
    for photo in card.photos or []:
        media_id = photo.get("media_id")
        if media_id:
            urls.append(sign_media_path(UUID(str(media_id))))
    return urls


# ─── Каталог ─────────────────────────────────────────────────────────────────


@router.get("/learn/products", response_model=ProductListResponse)
async def list_products(
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None

    categories = (
        (
            await db.execute(
                select(ProductCategory).order_by(
                    ProductCategory.position, ProductCategory.title
                )
            )
        )
        .scalars()
        .all()
    )

    if manage and lifecycle.can(role, "publisher"):
        stmt = select(ProductCard)
    elif manage and role == "author":
        stmt = select(ProductCard).where(
            (ProductCard.created_by == principal.employee_id)
            | (
                (ProductCard.status == "published")
                & visible_filter(ProductCard, profile_id or UUID(int=0))
            )
        )
    else:
        stmt = select(ProductCard).where(
            ProductCard.status == "published",
            visible_filter(ProductCard, profile_id or UUID(int=0)),
        )
    cards = list(
        (await db.execute(stmt.order_by(ProductCard.position, ProductCard.title)))
        .scalars()
        .all()
    )

    viewed: set[UUID] = set()
    if profile_id and cards:
        viewed = {
            r[0]
            for r in await db.execute(
                select(ViewHistory.object_id).where(
                    ViewHistory.profile_id == profile_id,
                    ViewHistory.object_type == _OBJECT_TYPE,
                    ViewHistory.object_id.in_([c.id for c in cards]),
                )
            )
        }

    links = await _resolve_links(db, [c.id for c in cards])
    items = []
    for card in cards:
        resp = ProductResponse.model_validate(card)
        resp.photo_urls = _photo_urls(card)
        resp.links = links.get(card.id, [])
        resp.viewed_by_me = card.id in viewed
        items.append(resp)
    return ProductListResponse(
        categories=[CategoryResponse.model_validate(c) for c in categories],
        items=items,
        content_role=role,
    )


@router.post("/learn/products/{product_id}/open", status_code=204)
async def open_product(
    product_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Факт открытия карточки: view_history + балл за первое знакомство."""
    role = await resolve_content_role(db, principal)
    card = await _get_card_or_404(db, product_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _card_visible_to(db, card, principal, role, profile.id):
        raise HTTPException(status_code=404, detail="Карточка не найдена")

    stmt = pg_insert(ViewHistory).values(
        profile_id=profile.id,
        object_type=_OBJECT_TYPE,
        object_id=card.id,
        tenant_id=card.tenant_id,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["profile_id", "object_type", "object_id"],
            set_={
                "last_viewed_at": text("now()"),
                "view_count": ViewHistory.view_count + 1,
            },
        )
    )
    if card.status == "published":
        await award(
            db,
            tenant_id=card.tenant_id,
            profile_id=profile.id,
            event_type="product.first_view",
            object_type=_OBJECT_TYPE,
            object_id=card.id,
        )
    await db.commit()


# ─── CRUD карточек ───────────────────────────────────────────────────────────


def _apply_upsert(card: ProductCard, body: ProductUpsert) -> None:
    fields = body.model_dump(exclude_unset=True, exclude={"links", "photos"})
    for name, value in fields.items():
        setattr(card, name, value)
    if body.photos is not None:
        card.photos = [{"media_id": str(p.media_id)} for p in body.photos]


async def _replace_links(
    db: AsyncSession, card: ProductCard, body: ProductUpsert
) -> None:
    if body.links is None:
        return
    await db.execute(
        delete(ProductCardLink).where(ProductCardLink.product_id == card.id)
    )
    for i, link in enumerate(body.links):
        db.add(
            ProductCardLink(
                tenant_id=card.tenant_id,
                product_id=card.id,
                object_type=link.object_type,
                object_id=link.object_id,
                position=i,
            )
        )


async def _card_response(db: AsyncSession, card: ProductCard) -> ProductResponse:
    resp = ProductResponse.model_validate(card)
    resp.photo_urls = _photo_urls(card)
    resp.links = (await _resolve_links(db, [card.id])).get(card.id, [])
    return resp


@router.post("/learn/products", response_model=ProductResponse, status_code=201)
async def create_product(
    body: ProductUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    await require_content_role(db, principal, "author")
    if not body.title:
        raise HTTPException(status_code=422, detail="Название обязательно")
    card = ProductCard(
        tenant_id=principal.tenant_id,
        title=body.title,
        owner_id=principal.employee_id,
        created_by=principal.employee_id,
    )
    db.add(card)
    await db.flush()
    _apply_upsert(card, body)
    await _replace_links(db, card, body)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=_OBJECT_TYPE,
        object_id=card.id,
        object_label=card.title,
    )
    await db.commit()
    await db.refresh(card)
    return await _card_response(db, card)


@router.patch("/learn/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    body: ProductUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    role = await require_content_role(db, principal, "author")
    card = await _get_card_or_404(db, product_id)
    _require_manage(card, principal, role)
    _apply_upsert(card, body)
    await _replace_links(db, card, body)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=card.id,
        object_label=card.title,
    )
    await _reindex(db, card)
    await db.commit()
    await db.refresh(card)
    return await _card_response(db, card)


@router.delete("/learn/products/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    card = await _get_card_or_404(db, product_id)
    _require_manage(card, principal, role)
    if card.published_at is not None:
        raise HTTPException(status_code=409, detail="Карточка публиковалась — используйте архив")
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=_OBJECT_TYPE,
        object_id=card.id,
        object_label=card.title,
    )
    await delete_document(db, object_type=_OBJECT_TYPE, object_id=card.id)
    await db.delete(card)
    await db.commit()


@router.post("/learn/products/{product_id}/status", response_model=ProductResponse)
async def change_product_status(
    product_id: UUID,
    body: StatusBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    role = await require_content_role(db, principal, "author")
    card = await _get_card_or_404(db, product_id)
    _require_manage(card, principal, role)
    lifecycle.transition(
        db,
        card,
        body.status,
        actor_id=principal.employee_id,
        role=role,
        tenant_id=principal.tenant_id,
        object_type=_OBJECT_TYPE,
        object_label=card.title,
    )
    await _reindex(db, card)
    await db.commit()
    await db.refresh(card)
    return await _card_response(db, card)


@router.put("/learn/products/{product_id}/audience", response_model=ProductResponse)
async def set_product_audience(
    product_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    await require_content_role(db, principal, "publisher")
    card = await _get_card_or_404(db, product_id)
    try:
        audience_id, _diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=card.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"{_OBJECT_TYPE}:{card.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    card.audience_id = audience_id
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=_OBJECT_TYPE,
        object_id=card.id,
        object_label=card.title,
    )
    await _reindex(db, card)
    await db.commit()
    await db.refresh(card)
    return await _card_response(db, card)


# ─── Категории ───────────────────────────────────────────────────────────────


@router.post("/learn/product-categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    await require_content_role(db, principal, "publisher")
    max_pos = (
        await db.execute(select(ProductCategory.position).order_by(
            ProductCategory.position.desc()
        ).limit(1))
    ).scalar_one_or_none()
    category = ProductCategory(
        tenant_id=principal.tenant_id,
        title=body.title,
        position=(max_pos if max_pos is not None else -1) + 1,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return CategoryResponse.model_validate(category)


@router.patch(
    "/learn/product-categories/{category_id}", response_model=CategoryResponse
)
async def rename_category(
    category_id: UUID,
    body: CategoryBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    await require_content_role(db, principal, "publisher")
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    category.title = body.title
    await db.commit()
    await db.refresh(category)
    return CategoryResponse.model_validate(category)


@router.delete("/learn/product-categories/{category_id}", status_code=204)
async def delete_category(
    category_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    in_use = (
        await db.execute(
            select(ProductCard.id).where(ProductCard.category_id == category_id).limit(1)
        )
    ).scalar_one_or_none()
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="В категории есть карточки — сначала перенесите их",
        )
    await db.delete(category)
    await db.commit()
