"""Integration-тесты Ф4: видимость карточек, first_view, линки, витрина."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.learn_home import learn_home, learn_profile
from app.api.products import list_products, open_product
from app.models.activity import ActivityEvent
from app.models.audience import Audience
from app.models.library import LibraryMaterial
from app.models.org import Position, Store
from app.models.product import ProductCard, ProductCardLink
from app.models.survey import Survey
from tests.integration.test_courses import _mk_course, _mk_member

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.services import notify_batch

    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _mk_card(db: AsyncSession, tenant_id: uuid.UUID, **kw) -> ProductCard:
    card = ProductCard(
        tenant_id=tenant_id,
        title=kw.pop("title", "Латте 250"),
        status=kw.pop("status", "published"),
        **kw,
    )
    db.add(card)
    await db.flush()
    return card


async def test_card_visibility_by_audience(db: AsyncSession, tenant_id: uuid.UUID):
    member, _profile = await _mk_member(db, tenant_id, email="barista@t.ru")

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    restricted = await _mk_card(db, tenant_id, title="Скрытый", audience_id=audience.id)
    open_card = await _mk_card(db, tenant_id, title="Открытый")
    await _mk_card(db, tenant_id, title="Черновик", status="draft")

    listing = await list_products(False, member, db)
    titles = {i.title for i in listing.items}
    assert titles == {"Открытый"}
    assert restricted.id not in {i.id for i in listing.items}
    assert open_card.id in {i.id for i in listing.items}


async def test_first_view_idempotent(db: AsyncSession, tenant_id: uuid.UUID):
    member, profile = await _mk_member(db, tenant_id, email="barista2@t.ru")
    card = await _mk_card(db, tenant_id)

    await open_product(card.id, member, db)
    await open_product(card.id, member, db)

    events = (
        (
            await db.execute(
                select(ActivityEvent).where(
                    ActivityEvent.profile_id == profile.id,
                    ActivityEvent.event_type == "product.first_view",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert float(events[0].points) == 0.5

    listing = await list_products(False, member, db)
    row = next(i for i in listing.items if i.id == card.id)
    assert row.viewed_by_me is True


async def test_links_resolved_and_dead_hidden(db: AsyncSession, tenant_id: uuid.UUID):
    member, _profile = await _mk_member(db, tenant_id, email="barista3@t.ru")
    course, _lessons = await _mk_course(db, tenant_id, lesson_count=1)
    card = await _mk_card(db, tenant_id)
    db.add(
        ProductCardLink(
            tenant_id=tenant_id,
            product_id=card.id,
            object_type="course",
            object_id=course.id,
            position=0,
        )
    )
    db.add(
        ProductCardLink(
            tenant_id=tenant_id,
            product_id=card.id,
            object_type="material",
            object_id=uuid.uuid4(),  # несуществующий → скрыт
            position=1,
        )
    )
    await db.flush()

    listing = await list_products(False, member, db)
    row = next(i for i in listing.items if i.id == card.id)
    assert len(row.links) == 1
    assert row.links[0].title == course.title
    assert row.links[0].url_path == f"/learn/courses/{course.id}"


async def test_home_blocks(db: AsyncSession, tenant_id: uuid.UUID):
    member, profile = await _mk_member(db, tenant_id, email="newbie2@t.ru")

    # Незавершённый обязательный курс.
    course, _lessons = await _mk_course(
        db, tenant_id, lesson_count=1, course_type="mandatory", title="Онбординг"
    )
    # Обязательное ознакомление.
    material = LibraryMaterial(
        tenant_id=tenant_id,
        title="Регламент кассы",
        kind="link",
        url="https://example.com",
        requires_acknowledgement=True,
        status="published",
    )
    db.add(material)
    # Активный опрос.
    survey = Survey(tenant_id=tenant_id, title="Пульс недели", kind="pulse", status="published")
    db.add(survey)
    await db.flush()

    home = await learn_home(member, db)
    assert any(c.title == "Онбординг" for c in home.courses)
    assert any(a.title == "Регламент кассы" for a in home.pending_acks)
    assert any(s.title == "Пульс недели" for s in home.surveys)
    assert home.rating is not None


async def test_learn_profile_tenure(db: AsyncSession, tenant_id: uuid.UUID):
    member, profile = await _mk_member(db, tenant_id, email="veteran@t.ru")
    pos = Position(tenant_id=tenant_id, name="Бариста")
    store = Store(tenant_id=tenant_id, name="П14")
    db.add_all([pos, store])
    await db.flush()
    profile.position_id = pos.id
    profile.store_id = store.id
    profile.hired_at = date.today() - timedelta(days=100)
    await db.flush()

    resp = await learn_profile(member, db)
    assert resp.position_name == "Бариста"
    assert resp.store_name == "П14"
    assert resp.tenure_days == 100
    assert resp.avatar_url and str(member.employee_id) in resp.avatar_url
