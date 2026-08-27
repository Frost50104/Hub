"""Избранное + недавно просмотренное (Ф2, ТЗ §11).

Заголовки и ссылки объектов берутся из `search_documents`, куда попадает только
ОПУБЛИКОВАННОЕ. Отсюда два следствия, и оба важны для экрана избранного:

- объект, снятый с публикации, названия не имеет — но из списка НЕ исчезает
  (LEFT JOIN + строка «недоступно сейчас»). Молча пропавшая звезда выглядит как
  «избранное не сохраняется», и это ровно та жалоба, с которой всё началось;
- подсветка звёзд по этому списку врала бы дважды — из-за лимита и из-за
  индекса. Для неё есть отдельная ручка `/learn/favorites/ids`: только пары
  «тип:id», без join и без лимита.
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

# Заголовка у недоступного объекта нет — в индексе его попросту не осталось.
# Тип назвать всё же можно: «Документ (недоступен)» честнее, чем пустая строка.
FALLBACK_TITLE = {
    "library_material": "Документ",
    "news_post": "Новость",
    "course": "Курс",
    "product": "Товар",
}


class FavoriteToggleBody(BaseModel):
    object_type: str = Field(max_length=32)
    object_id: UUID


class FavoriteItem(BaseModel):
    object_type: str
    object_id: UUID
    title: str
    url_path: str
    created_at: datetime | None = None
    # None у ссылки = объекта нет в индексе: черновик, архив или снятая
    # публикация. Клиент рисует такую строку неактивной, а не прячет.
    available: bool = True


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


class FavoriteIds(BaseModel):
    """Ключи «тип:id» — ровно то, что нужно звёздочкам в списках."""

    keys: list[str]


@router.get("/learn/favorites/ids", response_model=FavoriteIds)
async def list_favorite_ids(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> FavoriteIds:
    """Плоский список ключей — для подсветки звёзд в библиотеке, курсах и
    ассортименте.

    Отдельно от `/learn/favorites` НЕ ради экономии: тот список ограничен 50
    записями и join'ится с индексом публикаций, то есть у активного сотрудника
    часть звёзд просто не загорелась бы. Здесь нет ни лимита, ни join'а — сама
    отметка не зависит от того, опубликован ли объект сейчас.

    Без учебного профиля отдаём пусто, а не 404: звезду в этом случае прячет
    клиент, и падать на чтении незачем.
    """
    profile = await get_profile(db, principal)
    if profile is None:
        return FavoriteIds(keys=[])
    rows = await db.execute(
        select(Favorite.object_type, Favorite.object_id).where(
            Favorite.profile_id == profile.id
        )
    )
    return FavoriteIds(keys=[f"{object_type}:{object_id}" for object_type, object_id in rows])


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
        # LEFT, а не INNER: снятый с публикации объект обязан остаться в списке
        # пометкой «недоступно сейчас». INNER выбрасывал его молча, и человек
        # видел, как избранное «само рассасывается».
        .outerjoin(
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
            title=title or FALLBACK_TITLE.get(fav.object_type, "Объект"),
            url_path=url_path or "",
            created_at=fav.created_at,
            available=url_path is not None,
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
