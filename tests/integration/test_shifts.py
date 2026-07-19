"""Integration-тесты Ф7: матчинг отклика (должность+курсы), auto_confirm,
accept с отклонением остальных, withdraw назначенного, отмена."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.shifts import (
    ApplyBody,
    PostingCreate,
    accept_application,
    apply,
    cancel_posting,
    create_posting,
    list_shifts,
    withdraw,
)
from app.models.org import Position, Store
from app.models.progress import CourseProgress
from app.models.shift import ShiftApplication, ShiftPosting
from tests.integration.test_courses import _mk_course, _mk_member

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.api import shifts as shifts_api
    from app.services import notify_batch

    async def _noop_rate_limit(**kw) -> None:
        return None

    monkeypatch.setattr(shifts_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _setup(db: AsyncSession, tenant_id: uuid.UUID, *, email_prefix: str):
    """Админ-менеджер + бариста нужной должности + магазин."""
    manager = (await _mk_member(db, tenant_id, email=f"{email_prefix}-mgr@t.ru"))[0]
    # hub-admin роль → scope all.
    manager.product_roles["hub"] = "admin"
    barista, barista_profile = await _mk_member(
        db, tenant_id, email=f"{email_prefix}-seller@t.ru"
    )
    pos = Position(tenant_id=tenant_id, name="Бариста")
    store = Store(tenant_id=tenant_id, name="П14")
    db.add_all([pos, store])
    await db.flush()
    barista_profile.position_id = pos.id
    await db.flush()
    return manager, barista, barista_profile, pos, store


def _body(store, pos, **kw) -> PostingCreate:
    now = datetime.now(UTC)
    return PostingCreate(
        store_id=store.id,
        position_id=pos.id,
        starts_at=kw.pop("starts_at", now + timedelta(days=1)),
        ends_at=kw.pop("ends_at", now + timedelta(days=1, hours=8)),
        **kw,
    )


async def test_apply_requires_position_and_courses(
    db: AsyncSession, tenant_id: uuid.UUID
):
    manager, barista, barista_profile, pos, store = await _setup(
        db, tenant_id, email_prefix="s1"
    )
    course, _ = await _mk_course(db, tenant_id, lesson_count=1, title="Бариста-базовый")

    posting = await create_posting(
        _body(store, pos, required_course_ids=[course.id]), manager, db
    )

    #不та должность: другой сотрудник без position.
    other, _other_profile = await _mk_member(db, tenant_id, email="s1-other@t.ru")
    with pytest.raises(HTTPException) as exc:
        await apply(posting.id, ApplyBody(), other, db)
    assert exc.value.status_code == 403

    # Должность есть, курс не завершён → 409 с названием курса.
    with pytest.raises(HTTPException) as exc:
        await apply(posting.id, ApplyBody(), barista, db)
    assert exc.value.status_code == 409
    assert "Бариста-базовый" in exc.value.detail

    # Завершил курс → отклик проходит.
    db.add(
        CourseProgress(
            profile_id=barista_profile.id,
            course_id=course.id,
            tenant_id=tenant_id,
            lessons_completed=1,
            lessons_total=1,
            completed_at=datetime.now(UTC),
        )
    )
    await db.flush()
    await apply(posting.id, ApplyBody(comment="Готов выйти"), barista, db)

    app_row = (
        await db.execute(
            select(ShiftApplication).where(
                ShiftApplication.posting_id == posting.id,
                ShiftApplication.profile_id == barista_profile.id,
            )
        )
    ).scalar_one()
    assert app_row.status == "pending"

    # Повторный отклик → 409.
    with pytest.raises(HTTPException) as exc:
        await apply(posting.id, ApplyBody(), barista, db)
    assert exc.value.status_code == 409


async def test_auto_confirm_assigns_immediately(db: AsyncSession, tenant_id: uuid.UUID):
    manager, barista, barista_profile, pos, store = await _setup(
        db, tenant_id, email_prefix="s2"
    )
    posting = await create_posting(_body(store, pos, auto_confirm=True), manager, db)
    await apply(posting.id, ApplyBody(), barista, db)

    row = (
        await db.execute(select(ShiftPosting).where(ShiftPosting.id == posting.id))
    ).scalar_one()
    assert row.status == "assigned"
    assert row.assigned_profile_id == barista_profile.id


async def test_accept_declines_others(db: AsyncSession, tenant_id: uuid.UUID):
    manager, barista, barista_profile, pos, store = await _setup(
        db, tenant_id, email_prefix="s3"
    )
    second, second_profile = await _mk_member(db, tenant_id, email="s3-second@t.ru")
    second_profile.position_id = pos.id
    await db.flush()

    posting = await create_posting(_body(store, pos), manager, db)
    await apply(posting.id, ApplyBody(), barista, db)
    await apply(posting.id, ApplyBody(), second, db)

    first_app = (
        await db.execute(
            select(ShiftApplication).where(
                ShiftApplication.posting_id == posting.id,
                ShiftApplication.profile_id == barista_profile.id,
            )
        )
    ).scalar_one()
    await accept_application(first_app.id, manager, db)

    rows = (
        (
            await db.execute(
                select(ShiftApplication).where(ShiftApplication.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    statuses = {r.profile_id: r.status for r in rows}
    assert statuses[barista_profile.id] == "accepted"
    assert statuses[second_profile.id] == "declined"

    row = (
        await db.execute(select(ShiftPosting).where(ShiftPosting.id == posting.id))
    ).scalar_one()
    assert row.status == "assigned"

    # Назначенный отказался → смена снова open.
    await withdraw(posting.id, barista, db)
    await db.flush()
    row2 = (
        await db.execute(select(ShiftPosting).where(ShiftPosting.id == posting.id))
    ).scalar_one()
    assert row2.status == "open" and row2.assigned_profile_id is None


async def test_cancel_and_employee_listing(db: AsyncSession, tenant_id: uuid.UUID):
    manager, barista, barista_profile, pos, store = await _setup(
        db, tenant_id, email_prefix="s4"
    )
    posting = await create_posting(_body(store, pos), manager, db)

    listing = await list_shifts(False, barista, db)
    mine = next(i for i in listing.items if i.id == posting.id)
    assert mine.can_apply is True
    assert mine.store_name == "П14"

    await apply(posting.id, ApplyBody(), barista, db)
    await cancel_posting(posting.id, manager, db)

    row = (
        await db.execute(select(ShiftPosting).where(ShiftPosting.id == posting.id))
    ).scalar_one()
    assert row.status == "cancelled"

    # Отменённая смена с моим откликом остаётся видимой в моём списке.
    listing2 = await list_shifts(False, barista, db)
    cancelled = next(i for i in listing2.items if i.id == posting.id)
    assert cancelled.status == "cancelled"
    assert cancelled.my_application_status == "pending"
