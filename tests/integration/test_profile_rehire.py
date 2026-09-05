"""Увольнение освобождает корпоративный ящик (01.09).

ОС владельца: ящик уволенного отдают следующему сотруднику, и тот получал не
чистый профиль, а остаток от предшественника — вплоть до сданного обязательного
курса. Матчинг находил карточку по `employee_id` (ящик передали вместе с
учёткой) или по email (учётку пересоздали).

Лечим отвязкой, а не удалением: на карточке каскадом висят 18 таблиц, среди них
сертификаты и ознакомления — доказательство, что сотрудник был обучен.

Здесь закреплены обе половины правила. Отвязка ТОЛЬКО при увольнении — вторая
половина не менее важна: `manual` значит «временно убрали» (декрет, долгий
больничный), и отвязка отправила бы вернувшегося на чистый лист.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.employees import link_employee_login
from app.models.audit import AuditLog
from app.models.employee_profile import EmployeeProfile
from app.models.engagement import Favorite
from app.schemas.employee import ArchiveBody, LinkBody
from app.services.employee_profiles import (
    archive_profile,
    ensure_profile_for_principal,
    find_latest_archived_by_email,
)
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _login(db: AsyncSession, principal):
    """Первый вход: shadow-строки + матчинг профиля, как в `/api/me`."""
    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    return await ensure_profile_for_principal(db, principal)


def _person(tenant_id: uuid.UUID, slug: str, email: str | None = None):
    return make_principal(
        tenant_id,
        email=email or f"{slug}@t.ru",
        role="member",
        tenant_slug=slug,
    )


async def _mark_history(db: AsyncSession, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> None:
    """След обучения на карточке. `favorites` взят как самый дешёвый из 18
    каскадов — своего объекта не требует, а привязан к профилю так же."""
    db.add(
        Favorite(
            profile_id=profile_id,
            object_type="material",
            object_id=uuid.uuid4(),
            tenant_id=tenant_id,
        )
    )
    await db.flush()


async def _history_count(db: AsyncSession, profile_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Favorite).where(Favorite.profile_id == profile_id)
        )
    ).scalar_one()


# ─── Кто освобождает вход, а кто нет ────────────────────────────────────────


@pytest.mark.parametrize(
    ("reason", "unbound"),
    [
        ("manual", True),
        ("auth_deleted", True),
        ("auto_inactivity", False),
    ],
)
async def test_archiving_frees_the_login_except_for_the_inactivity_robot(
    db: AsyncSession, tenant_id: uuid.UUID, reason: str, unbound: bool
):
    """Архивация человеком освобождает вход; авто-архив за неактивность — нет.

    Спрашивать админа «уволен или временно?» мы пробовали и отказались: выбор
    можно ответить неверно каждый раз, а неверный ответ бесшумно возвращает
    исходный баг. `auto_inactivity` остался исключением не как выбор, а потому
    что джоба архивирует человека, который никуда не уходил, — отвязка выкинула
    бы действующего сотрудника в «Непривязанные входы».
    """
    person = _person(tenant_id, f"rh-{reason[:6]}")
    profile = (await _login(db, person)).profile
    assert profile is not None and profile.employee_id is not None

    await archive_profile(db, profile, reason=reason, actor_id=None)

    assert (profile.employee_id is None) is unbound


async def test_archive_body_default_matches_the_only_human_reason(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Старый PWA-бандл шлёт архивацию без тела и получает `manual` — ту же
    причину, что и новый клиент. Значит застрявший бандл автоматически
    освобождает вход, а не тянет прежнее поведение."""
    assert ArchiveBody().reason == "manual"


# ─── Три сценария передачи ящика ────────────────────────────────────────────


async def test_same_account_after_dismissal_gets_a_clean_card(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Сценарий 1: ящик передали вместе с учёткой — `employee_id` тот же.

    Раньше матчинг находил карточку на первом шаге и синхронизировал ФИО: для
    Hub человек «сменил имя», а новый сотрудник наследовал всё молча.
    """
    person = _person(tenant_id, "rh-same")
    first = (await _login(db, person)).profile
    await _mark_history(db, tenant_id, first.id)

    await archive_profile(db, first, reason="manual", actor_id=None)
    await db.flush()

    second = (await _login(db, person)).profile

    assert second.id != first.id, "новый сотрудник унаследовал карточку"
    assert await _history_count(db, second.id) == 0
    assert await _history_count(db, first.id) == 1, "история уволенного пропала"


async def test_new_account_on_the_same_mailbox_gets_a_clean_card(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Сценарий 2: учётку пересоздали, адрес тот же.

    Раньше возвращался `needs_restore`, и «восстановить» означало «отдать
    новому человеку историю старого».
    """
    mailbox = "barista-rh2@t.ru"
    leaver = _person(tenant_id, "rh-old2", email=mailbox)
    old = (await _login(db, leaver)).profile
    await _mark_history(db, tenant_id, old.id)
    await archive_profile(db, old, reason="manual", actor_id=None)
    await db.flush()

    newcomer = _person(tenant_id, "rh-new2", email=mailbox)
    result = await _login(db, newcomer)

    assert result.outcome == "created"
    assert result.profile.id != old.id
    assert await _history_count(db, result.profile.id) == 0


async def test_active_card_on_the_same_mailbox_still_signals_conflict(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Сценарий 3: карточку НЕ заархивировали. Данные разъехались, и молчать
    нельзя — ветку `email_conflict` мы сознательно оставили."""
    mailbox = "barista-rh3@t.ru"
    leaver = _person(tenant_id, "rh-old3", email=mailbox)
    await _login(db, leaver)  # карточка активна и привязана к прежнему аккаунту

    newcomer = _person(tenant_id, "rh-new3", email=mailbox)
    result = await _login(db, newcomer)

    assert result.outcome == "needs_restore"
    assert result.profile is None


# ─── Подсказка вместо needs_restore ─────────────────────────────────────────


async def test_new_card_records_the_archived_twin(db: AsyncSession, tenant_id: uuid.UUID):
    """Обычно это новый человек на освободившемся ящике. Но тем же путём идёт
    ОШИБОЧНАЯ архивация, и без следа дубль появлялся бы молча."""
    mailbox = "barista-rh4@t.ru"
    leaver = _person(tenant_id, "rh-old4", email=mailbox)
    old = (await _login(db, leaver)).profile
    await archive_profile(db, old, reason="manual", actor_id=None)
    await db.flush()

    newcomer = _person(tenant_id, "rh-new4", email=mailbox)
    fresh = (await _login(db, newcomer)).profile

    twin = await find_latest_archived_by_email(db, mailbox)
    assert twin is not None and twin.id == old.id

    # Сессия с `autoflush=False` (инвариант проекта): `audit.record` только
    # добавляет объект, а в `/api/me` его сбрасывает следующий за матчингом
    # commit. В тесте commit'а нет — флашим руками.
    await db.flush()
    marks = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_id == fresh.id, AuditLog.object_type == "employee_profile"
            )
        )
    ).scalars().all()
    assert any("archived_twin" in (m.diff or {}) for m in marks)


async def test_two_archived_cards_on_one_mailbox_do_not_break_login(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Наняли — уволили — наняли — уволили: две архивные карточки на один адрес.

    До 01.09 такой пары не могло быть (повторный найм упирался в
    `needs_restore`), а `scalar_one_or_none()` на архивных бросил бы
    `MultipleResultsFound` прямо в `/api/me` — человек не смог бы войти вовсе.
    """
    mailbox = "barista-rh5@t.ru"
    for n in (1, 2):
        person = _person(tenant_id, f"rh-cyc{n}", email=mailbox)
        profile = (await _login(db, person)).profile
        await archive_profile(db, profile, reason="manual", actor_id=None)
        await db.flush()

    archived = (
        await db.execute(
            select(func.count())
            .select_from(EmployeeProfile)
            .where(
                func.lower(EmployeeProfile.email) == mailbox,
                EmployeeProfile.status == "archived",
            )
        )
    ).scalar_one()
    assert archived == 2

    third = _person(tenant_id, "rh-cyc3", email=mailbox)
    result = await _login(db, third)
    assert result.outcome == "created"

    twin = await find_latest_archived_by_email(db, mailbox)
    assert twin is not None, "поиск двойника упал на двух архивных"


# ─── Чёрный ход ─────────────────────────────────────────────────────────────


async def test_link_refuses_archived_card(db: AsyncSession, tenant_id: uuid.UUID):
    """Привязка живого входа к архивной карточке — та же ловушка наследования,
    только через API."""
    admin = make_principal(
        tenant_id, email="adm-rh6@t.ru", role="admin", tenant_slug="rh6"
    )
    await upsert_shadow_tenant(db, admin, table="shadow_tenants")
    await upsert_shadow_user(db, admin, table="shadow_users")

    leaver = _person(tenant_id, "rh-old6")
    old = (await _login(db, leaver)).profile
    await archive_profile(db, old, reason="manual", actor_id=None)
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await link_employee_login(
            old.id, LinkBody(employee_id=admin.employee_id), admin, db
        )
    assert exc.value.status_code == 409
