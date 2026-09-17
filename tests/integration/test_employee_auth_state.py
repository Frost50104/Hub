"""Статус «Приглашён(а) в auth» и единый расчёт статуса учётки (16.09).

Ручное заведение карточек закрыто, штат приходит из auth приглашениями. Пока
приглашение не принято, у карточки нет `employee_id`, и раньше она семь дней
показывала «Без учётки», хотя движение уже есть — зеркало `auth_invitations`
о нём знает. Статус считается ОДНОЙ функцией для экрана «Сотрудники» и
для «Прогресса» — тест сеет одно и то же и спрашивает обоих.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.employees import list_employees
from app.models.employee_profile import EmployeeProfile
from app.models.shadow import AuthInvitation, ShadowUser
from app.services.learning_progress import _auth_states
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _admin_with_fresh_snapshot(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    principal = make_principal(
        tenant_id, email=f"adm-{slug}@t.ru", role="admin", tenant_slug=slug
    )
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    # Свежий снимок штата: без него любой непривязанный — осторожное not_linked.
    await db.execute(
        update(ShadowUser)
        .where(ShadowUser.employee_id == principal.employee_id)
        .values(staff_synced_at=datetime.now(UTC), hub_role="admin", auth_active=True)
    )
    return principal


async def _list(principal, db: AsyncSession, q: str):
    return await list_employees(
        status_filter="active",
        q=q,
        store_id=None,
        position_id=None,
        limit=100,
        offset=0,
        principal=principal,
        db=db,
    )


async def test_invited_card_is_reported_by_both_screens(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _admin_with_fresh_snapshot(db, tenant_id, "inv1")
    invited = EmployeeProfile(
        tenant_id=tenant_id, email="Invited.One@t.ru", full_name="Приглашённая Инв1"
    )
    plain = EmployeeProfile(
        tenant_id=tenant_id, email="plain.one@t.ru", full_name="Безучётки Инв1"
    )
    db.add_all([invited, plain])
    db.add(
        AuthInvitation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            # Регистр в зеркале — как прислал auth; сверка идёт по lower().
            email="invited.one@t.ru",
            full_name="Приглашённая Инв1",
            role="member",
            expires_at=None,
        )
    )
    await db.flush()

    page = await _list(admin, db, "Инв1")
    by_email = {row.email.lower(): row.auth_state for row in page.items}
    assert by_email["invited.one@t.ru"] == "invited"
    assert by_email["plain.one@t.ru"] == "no_account"

    states = await _auth_states(db, [invited, plain])
    assert states[invited.id] == "invited"
    assert states[plain.id] == "no_account"


async def test_linked_card_ignores_a_stale_invitation(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Приглашение на почту УЖЕ привязанной карточки ничего не значит:
    `employee_id` смотрится первым."""
    admin = await _admin_with_fresh_snapshot(db, tenant_id, "inv2")
    linked = EmployeeProfile(
        tenant_id=tenant_id,
        email="linked.two@t.ru",
        full_name="Привязанная Инв2",
        employee_id=admin.employee_id,
    )
    db.add(linked)
    db.add(
        AuthInvitation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="linked.two@t.ru",
            full_name=None,
            role="member",
            expires_at=None,
        )
    )
    await db.flush()

    page = await _list(admin, db, "Инв2")
    assert page.items[0].auth_state == "not_logged_in"


# --- приглашения в выдаче списка (ОС владельца 17.09) ------------------------
#
# «"Приглашены в auth, ещё не приняли" всегда и на первом месте, а доступные
# фильтры влияют только на показ после этого блока». Обе причины были здесь, в
# ручке: зеркало приглашений отдавалось целиком и мимо поиска.


async def test_invitation_with_card_is_not_returned_twice(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Приглашение, у которого есть активная карточка, в `invitations` не едет.

    Иначе экран показывает человека дважды: строкой блока сверху и карточкой
    с бейджем «Приглашён(а)» ниже. На проде так дублировались 62 строки из 69.
    """
    admin = await _admin_with_fresh_snapshot(db, tenant_id, "inv-dup")
    card = EmployeeProfile(
        tenant_id=tenant_id, email="dup.one@t.ru", full_name="Дубль Инвдуп"
    )
    db.add(card)
    db.add(
        AuthInvitation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="Dup.One@t.ru",  # регистр как прислал auth — сверка по lower()
            full_name="Дубль Инвдуп",
            role="member",
            expires_at=None,
        )
    )
    await db.flush()

    page = await _list(admin, db, "Инвдуп")
    assert [r.email.lower() for r in page.items] == ["dup.one@t.ru"]
    assert [i.email.lower() for i in page.invitations] == []


async def test_invitation_without_card_is_returned(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """А вот у кого карточки нет — единственный, кого показать больше негде."""
    admin = await _admin_with_fresh_snapshot(db, tenant_id, "inv-solo")
    db.add(
        AuthInvitation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="solo.inv@t.ru",
            full_name="Одиночка Инвсоло",
            role="member",
            expires_at=None,
        )
    )
    await db.flush()

    page = await _list(admin, db, "Инвсоло")
    assert [i.email for i in page.invitations] == ["solo.inv@t.ru"]


async def test_invitations_obey_search(db: AsyncSession, tenant_id: uuid.UUID):
    """Строка, не слушающаяся поиска, ведёт себя как приклеенная — ровно то,
    что владелец и увидел."""
    admin = await _admin_with_fresh_snapshot(db, tenant_id, "inv-q")
    for email, name in (
        ("match.inv@t.ru", "Нужный Инвкью"),
        ("other.inv@t.ru", "Посторонний Инвкью2"),
    ):
        db.add(
            AuthInvitation(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                email=email,
                full_name=name,
                role="member",
                expires_at=None,
            )
        )
    await db.flush()

    assert [i.email for i in (await _list(admin, db, "Нужный")).invitations] == [
        "match.inv@t.ru"
    ]
    # Поиск по почте тоже: `match_condition` смотрит оба поля.
    assert [i.email for i in (await _list(admin, db, "other.inv")).invitations] == [
        "other.inv@t.ru"
    ]
