"""«Входящие»: страницы по курсору `before_id` и массовые отметки (19.10).

Курсор и порядок списка — обе оси по `id`: при сортировке по `created_at`
строка перекрывшейся транзакции (время — начало транзакции, id — момент
INSERT) на границе страницы пропадала или дублировалась. Здесь `created_at`
нарочно перемешан относительно `id`, чтобы тест ловил именно это.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from signaris_auth import Principal
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.notifications import list_notifications, set_read_state
from app.models.notification import Notification
from app.schemas.notification import ReadStateUpdate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

PAGE = 50
FETCH = PAGE + 1


def _person(tenant_id: uuid.UUID, tag: str, name: str) -> Principal:
    return make_principal(
        tenant_id,
        email=f"{name}-{uuid.uuid4().hex[:6]}@test.ru",
        full_name=name,
        tenant_slug=f"inbox-{tag}-{tenant_id.hex[:8]}",
    )


async def _note(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    is_read: bool = False,
    created_at: datetime | None = None,
) -> Notification:
    extra = {"created_at": created_at} if created_at is not None else {}
    n = Notification(
        tenant_id=tenant_id,
        employee_id=employee_id,
        kind="task.assigned_to_me",
        title="Вам назначена задача",
        body="…",
        url=None,
        payload=None,
        is_read=is_read,
        read_at=datetime.now(UTC) if is_read else None,
        **extra,
    )
    db.add(n)
    await db.flush()
    return n


async def _walk(db: AsyncSession, me: Principal, *, unread_only: bool) -> tuple[list[int], int]:
    """Листает как клиент: `limit = 51`, 51-я строка — признак следующей страницы."""
    seen: list[int] = []
    before: int | None = None
    pages = 0
    while True:
        page = await list_notifications(
            unread_only=unread_only, limit=FETCH, before_id=before, principal=me, db=db
        )
        pages += 1
        if len(page) > PAGE:
            seen.extend(n.id for n in page[:PAGE])
            before = page[PAGE - 1].id
            continue
        seen.extend(n.id for n in page)
        return seen, pages


async def test_list_pages_by_id_without_gaps_or_dups(db: AsyncSession, tenant_id: uuid.UUID):
    me = _person(tenant_id, "pages", "Листатель")
    await _register(db, me)
    base = datetime.now(UTC) - timedelta(days=30)
    offsets = list(range(120))
    random.Random(42).shuffle(offsets)  # noqa: S311 — детерминированная перестановка
    ids: list[int] = []
    for off in offsets:
        n = await _note(
            db,
            tenant_id=tenant_id,
            employee_id=me.employee_id,
            created_at=base + timedelta(minutes=off),
        )
        ids.append(n.id)
    await db.commit()

    seen, pages = await _walk(db, me, unread_only=False)
    assert pages == 3, "120 строк = 50 + 50 + 20"
    assert seen == sorted(ids, reverse=True), "ни пропусков, ни дублей, id строго убывают"

    # Прочитана каждая вторая — окно «Непрочитанные» листается тем же курсором.
    await db.execute(
        update(Notification)
        .where(Notification.id.in_(ids[::2]))
        .values(is_read=True, read_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    seen, pages = await _walk(db, me, unread_only=True)
    assert pages == 2
    assert seen == sorted(ids[1::2], reverse=True)


async def test_set_read_state_bulk(db: AsyncSession, tenant_id: uuid.UUID):
    me = _person(tenant_id, "bulk", "Читатель")
    other = _person(tenant_id, "bulk", "Сосед")
    await _register(db, me)
    await _register(db, other)
    mine = [
        await _note(db, tenant_id=tenant_id, employee_id=me.employee_id, is_read=i < 2)
        for i in range(5)
    ]
    foreign = await _note(db, tenant_id=tenant_id, employee_id=other.employee_id)
    await db.commit()

    ids = [n.id for n in mine] + [foreign.id, foreign.id + 10_000_000]
    res = await set_read_state(ReadStateUpdate(ids=ids, is_read=True), principal=me, db=db)
    assert res.updated == 3, "две уже прочитаны, чужая и несуществующая не считаются"
    for n in mine:
        await db.refresh(n)
        assert n.is_read is True and n.read_at is not None
    await db.refresh(foreign)
    assert foreign.is_read is False, "чужая строка не тронута"

    back = [n.id for n in mine[:3]]
    res = await set_read_state(ReadStateUpdate(ids=back, is_read=False), principal=me, db=db)
    assert res.updated == 3
    for n in mine[:3]:
        await db.refresh(n)
        assert n.is_read is False and n.read_at is None, "непрочитано = оба поля сброшены"
    for n in mine[3:]:
        await db.refresh(n)
        assert n.is_read is True

    res = await set_read_state(ReadStateUpdate(ids=back, is_read=False), principal=me, db=db)
    assert res.updated == 0, "повтор идемпотентен"
