"""Избранное + недавно просмотренное (Ф2, ТЗ §11).

Заголовки/ссылки объектов берутся из search_documents (published) — избранный
или недавно открытый объект, который сняли с публикации, из списков исчезает.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from signaris_auth import Principal
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.engagement import FAVORITE_TYPES, Favorite
from app.models.library import ViewHistory
from app.models.search_document import SearchDocument
from app.services.org_scope import get_profile

router = APIRouter(tags=["learn-favorites"])


class FavoriteToggleBody(BaseModel):
    object_type: str = Field(max_length=32)
    object_id: UUID


class FavoriteItem(BaseModel):
    object_type: str
    object_id: UUID
    title: str
    url_path: str
    created_at: datetime | None = None


@router.post("/learn/favorites/toggle")
async def toggle_favorite(
    body: FavoriteToggleBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    if body.object_type not in FAVORITE_TYPES:
        raise HTTPException(status_code=422, detail="Недопустимый тип объекта")
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    existing = (
        await db.execute(
            select(Favorite).where(
                Favorite.profile_id == profile.id,
                Favorite.object_type == body.object_type,
                Favorite.object_id == body.object_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.execute(
            delete(Favorite).where(
                Favorite.profile_id == profile.id,
                Favorite.object_type == body.object_type,
                Favorite.object_id == body.object_id,
            )
        )
        await db.commit()
        return {"is_favorite": False}
    db.add(
        Favorite(
            profile_id=profile.id,
            object_type=body.object_type,
            object_id=body.object_id,
            tenant_id=principal.tenant_id,
        )
    )
    await db.commit()
    return {"is_favorite": True}


@router.get("/learn/favorites", response_model=list[FavoriteItem])
async def list_favorites(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[FavoriteItem]:
    profile = await get_profile(db, principal)
    if profile is None:
        return []
    rows = await db.execute(
        select(Favorite, SearchDocument.title, SearchDocument.url_path)
        .join(
            SearchDocument,
            (SearchDocument.object_type == Favorite.object_type)
            & (SearchDocument.object_id == Favorite.object_id),
        )
        .where(Favorite.profile_id == profile.id)
        .order_by(Favorite.created_at.desc())
        .limit(50)
    )
    return [
        FavoriteItem(
            object_type=fav.object_type,
            object_id=fav.object_id,
            title=title,
            url_path=url_path,
            created_at=fav.created_at,
        )
        for fav, title, url_path in rows
    ]


@router.get("/learn/recent", response_model=list[FavoriteItem])
async def list_recent(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[FavoriteItem]:
    """Недавно открытые материалы/новости (view_history × search_documents)."""
    profile = await get_profile(db, principal)
    if profile is None:
        return []
    rows = await db.execute(
        select(ViewHistory, SearchDocument.title, SearchDocument.url_path)
        .join(
            SearchDocument,
            (SearchDocument.object_type == ViewHistory.object_type)
            & (SearchDocument.object_id == ViewHistory.object_id),
        )
        .where(ViewHistory.profile_id == profile.id)
        .order_by(ViewHistory.last_viewed_at.desc())
        .limit(10)
    )
    return [
        FavoriteItem(
            object_type=vh.object_type,
            object_id=vh.object_id,
            title=title,
            url_path=url_path,
            created_at=vh.last_viewed_at,
        )
        for vh, title, url_path in rows
    ]
