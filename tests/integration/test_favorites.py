"""Избранное: ключи для звёздочек и список, который ничего не теряет.

Обе ручки читают одни и те же строки, но отвечают на разные вопросы, и именно
поэтому их две:

- `/learn/favorites/ids` — «отмечен ли объект»: без лимита и без склейки с
  индексом публикаций;
- `/learn/favorites` — «что у меня в избранном»: 50 последних, с названиями из
  индекса, а недоступное помечается, а не исчезает.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.favorites import (
    FavoriteToggleBody,
    list_favorite_ids,
    list_favorites,
    toggle_favorite,
)
from app.models.engagement import Favorite
from app.services.search_indexer import upsert_document
from tests.integration.test_courses import _mk_member

pytestmark = pytest.mark.integration


async def _indexed(db: AsyncSession, tenant_id: uuid.UUID, object_id: uuid.UUID, title: str):
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="library_material",
        object_id=object_id,
        title=title,
        snippet=None,
        url_path=f"/learn/library?m={object_id}",
    )


async def test_toggle_adds_and_removes(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _mk_member(db, tenant_id, email="fav-toggle@t.ru")
    await db.commit()
    target = uuid.uuid4()

    assert await toggle_favorite(
        FavoriteToggleBody(object_type="course", object_id=target), principal, db
    ) == {"is_favorite": True}
    ids = await list_favorite_ids(principal, db)
    assert ids.keys == [f"course:{target}"]

    assert await toggle_favorite(
        FavoriteToggleBody(object_type="course", object_id=target), principal, db
    ) == {"is_favorite": False}
    assert (await list_favorite_ids(principal, db)).keys == []


async def test_ids_do_not_depend_on_the_search_index(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Звезда горит и у неопубликованного объекта.

    Список избранного склеивается с `search_documents`, куда черновики не
    попадают. Если бы по нему же считалась подсветка, звезда у только что
    отмеченного черновика гасла бы сама — и выглядело бы это как «избранное не
    сохраняется».
    """
    principal, _profile = await _mk_member(db, tenant_id, email="fav-draft@t.ru")
    await db.commit()
    draft = uuid.uuid4()
    await toggle_favorite(
        FavoriteToggleBody(object_type="library_material", object_id=draft), principal, db
    )

    assert (await list_favorite_ids(principal, db)).keys == [f"library_material:{draft}"]


async def test_ids_are_not_capped_at_fifty(db: AsyncSession, tenant_id: uuid.UUID):
    """Список отдаёт 50 последних, ключи — все.

    У активного сотрудника избранного больше полусотни, и подсветка по списку
    гасила бы часть звёзд без всякой закономерности.
    """
    principal, profile = await _mk_member(db, tenant_id, email="fav-many@t.ru")
    for _ in range(55):
        db.add(
            Favorite(
                profile_id=profile.id,
                object_type="product",
                object_id=uuid.uuid4(),
                tenant_id=tenant_id,
            )
        )
    await db.commit()

    assert len((await list_favorite_ids(principal, db)).keys) == 55
    assert len(await list_favorites(principal, db)) == 50


async def test_unpublished_favorite_stays_in_the_list_marked(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """INNER JOIN выбрасывал такую запись молча — теперь она видна пометкой."""
    principal, _profile = await _mk_member(db, tenant_id, email="fav-gone@t.ru")
    live, gone = uuid.uuid4(), uuid.uuid4()
    await _indexed(db, tenant_id, live, "Действующий регламент")
    await db.commit()

    for object_id in (live, gone):
        await toggle_favorite(
            FavoriteToggleBody(object_type="library_material", object_id=object_id),
            principal,
            db,
        )

    items = {item.object_id: item for item in await list_favorites(principal, db)}
    assert set(items) == {live, gone}
    assert items[live].available is True
    assert items[live].title == "Действующий регламент"
    assert items[gone].available is False
    # Названия нет — подставляем тип, чтобы строка не была пустой.
    assert items[gone].title == "Документ"
    assert items[gone].url_path == ""


async def test_bad_object_type_is_refused(db: AsyncSession, tenant_id: uuid.UUID):
    """Тип — часть ключа: мусор в нём сделал бы звезду ненаходимой."""
    from fastapi import HTTPException

    principal, _profile = await _mk_member(db, tenant_id, email="fav-bad@t.ru")
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await toggle_favorite(
            FavoriteToggleBody(object_type="lesson", object_id=uuid.uuid4()), principal, db
        )
    assert exc.value.status_code == 422
