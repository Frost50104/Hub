"""Staff-sync (0052): pull штата из auth — тени, кеш ролей, карточки.

Фетчер страниц мокается monkeypatch'ем (respx в зависимостях нет): синк
структурирован как «фетчер + применение», транспорт в тестах не поднимается.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.models.shadow import AuthInvitation, ShadowUser
from app.services import staff_sync
from app.services.staff_sync import sync_staff

pytestmark = pytest.mark.integration


def _staff_row(tenant_id: uuid.UUID, **kw) -> dict:
    employee_id = kw.pop("employee_id", uuid.uuid4())
    return {
        "kind": "employee",
        "employee_id": str(employee_id),
        "tenant_id": str(tenant_id),
        "email": kw.pop("email", f"{uuid.uuid4().hex[:8]}@t.ru"),
        "full_name": kw.pop("full_name", "Из Auth"),
        "role": kw.pop("role", "member"),
        "is_active": kw.pop("is_active", True),
        "deleted_at": kw.pop("deleted_at", None),
        **kw,
    }


def _mock_fetch(monkeypatch, items: list[dict] | None):
    async def fake_fetch():
        return items

    monkeypatch.setattr(staff_sync, "_fetch_staff_pages", fake_fetch)


async def test_sync_creates_shadow_and_profile(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Учётка с hub-ролью появляется в Hub, НЕ дожидаясь первого входа:
    тень + карточка без last_activity_at (бейдж «не входил» честен)."""
    row = _staff_row(tenant_id, email="new-hire@t.ru", role="member")
    _mock_fetch(monkeypatch, [row])
    await db.commit()  # синк работает своими сессиями

    report = await sync_staff()
    assert report.available and report.profiles_created == 1

    shadow = (
        await db.execute(
            select(ShadowUser).where(ShadowUser.email == "new-hire@t.ru")
        )
    ).scalar_one()
    assert shadow.hub_role == "member" and shadow.auth_active is True
    assert shadow.staff_synced_at is not None

    profile = (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "new-hire@t.ru")
        )
    ).scalar_one()
    assert str(profile.employee_id) == row["employee_id"]
    assert profile.last_activity_at is None  # человек НЕ входил


async def test_sync_links_prepared_card_and_skips_conflicts(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """HR-карточка без привязки привязывается (как /link — без last_activity);
    активная карточка, привязанная к другому аккаунту, — конфликт, не трогаем."""
    prepared = EmployeeProfile(
        tenant_id=tenant_id, email="hr-card@t.ru", full_name="Заведённая HR"
    )
    other_eid = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=other_eid,
            tenant_id=tenant_id,
            email="taken@t.ru",
            full_name="Чужая привязка",
        )
    )
    await db.flush()
    other = EmployeeProfile(
        tenant_id=tenant_id,
        email="taken@t.ru",
        full_name="Чужая привязка",
        employee_id=other_eid,
    )
    db.add_all([prepared, other])
    await db.commit()

    rows = [
        _staff_row(tenant_id, email="HR-Card@t.ru"),
        _staff_row(tenant_id, email="taken@t.ru"),
    ]
    _mock_fetch(monkeypatch, rows)
    report = await sync_staff()
    assert report.profiles_linked == 1
    assert report.email_conflicts == 1

    await db.refresh(prepared)
    assert str(prepared.employee_id) == rows[0]["employee_id"]
    assert prepared.last_activity_at is None
    assert prepared.full_name == "Заведённая HR"  # имя HR не перетёрто до входа


async def test_sync_skips_archived_email_and_archives_deleted(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Архивная карточка с тем же email БЛОКИРУЕТ создание (требование 3
    auth: archive_profile(manual) обнуляет employee_id, и без проверки pull
    пересоздавал бы карточку через 15 минут после каждой ручной архивации);
    deleted в auth архивирует активную карточку (страховка фида)."""
    archived = EmployeeProfile(
        tenant_id=tenant_id,
        email="rehire@t.ru",
        full_name="Уволенный",
        status="archived",
    )
    victim_eid = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=victim_eid,
            tenant_id=tenant_id,
            email="gone@t.ru",
            full_name="Удалён в auth",
        )
    )
    await db.flush()
    victim = EmployeeProfile(
        tenant_id=tenant_id,
        email="gone@t.ru",
        full_name="Удалён в auth",
        employee_id=victim_eid,
    )
    db.add_all([archived, victim])
    await db.commit()

    rows = [
        _staff_row(tenant_id, email="rehire@t.ru"),
        _staff_row(
            tenant_id,
            email="gone@t.ru",
            employee_id=victim_eid,
            deleted_at="2026-09-02T00:00:00Z",
        ),
    ]
    _mock_fetch(monkeypatch, rows)
    report = await sync_staff()
    assert report.profiles_created == 0
    assert report.archived_skips == 1  # ручной архив не «воскресает» pull'ом
    assert report.archived == 1

    active_cards = (
        (
            await db.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.email == "rehire@t.ru",
                    EmployeeProfile.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    assert active_cards == []  # новую карточку заведёт только живой ВХОД

    await db.refresh(victim)
    assert victim.status == "archived" and victim.archive_reason == "auth_deleted"


async def test_sync_unavailable_and_idempotent(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """404/сеть → no-op с available=false; повторный прогон — без диффа."""
    _mock_fetch(monkeypatch, None)
    report = await sync_staff()
    assert report.available is False and report.shadows_upserted == 0

    row = _staff_row(tenant_id, email="twice@t.ru")
    _mock_fetch(monkeypatch, [row])
    first = await sync_staff()
    second = await sync_staff()
    assert first.profiles_created == 1
    assert second.profiles_created == 0 and second.profiles_linked == 0


async def test_sync_replaces_invitations(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Приглашения — снапшот: принятые/отозванные исчезают при следующем синке."""
    inv_id = uuid.uuid4()
    _mock_fetch(
        monkeypatch,
        [
            {
                "kind": "invitation",
                "invitation_id": str(inv_id),
                "tenant_id": str(tenant_id),
                "email": "invited@t.ru",
                "full_name": "Приглашённая",
                "role": "member",
                "invited_expires_at": "2026-09-09T00:00:00Z",
            }
        ],
    )
    report = await sync_staff()
    assert report.invitations == 1
    stored = (
        await db.execute(select(AuthInvitation).where(AuthInvitation.id == inv_id))
    ).scalar_one()
    assert stored.email == "invited@t.ru"

    # Приглашение принято → в следующем ответе его нет → строка исчезает.
    _mock_fetch(monkeypatch, [_staff_row(tenant_id, email="invited@t.ru")])
    await sync_staff()
    left = (
        await db.execute(select(AuthInvitation).where(AuthInvitation.id == inv_id))
    ).scalar_one_or_none()
    assert left is None


async def test_service_account_gets_shadow_and_link_but_no_new_profile(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Требование 1 auth: точка-кафе (account_kind=service, в имени адрес)
    получает тень с кешем роли, но НЕ новую учебную карточку — та раздала бы
    ей неотзываемую рассылку обязательных курсов. СУЩЕСТВУЮЩАЯ карточка при
    этом привязывается (решение владельца 04.09: карточки кафе остаются —
    на кассе точки открыт её аккаунт, а непривязанная карточка показывала
    «без учётки» при живой учётке)."""
    prepared = EmployeeProfile(
        tenant_id=tenant_id, email="cafe-card@t.ru", full_name="Энергетиков 8"
    )
    db.add(prepared)
    await db.commit()

    rows = [
        _staff_row(
            tenant_id,
            email="cafe@t.ru",
            full_name="Приморская 14",
            role="viewer",
            account_kind="service",
        ),
        _staff_row(
            tenant_id,
            email="CAFE-Card@t.ru",
            full_name="Энергетиков 8",
            role="viewer",
            account_kind="service",
        ),
    ]
    _mock_fetch(monkeypatch, rows)
    report = await sync_staff()
    assert report.service_accounts == 2
    assert report.profiles_created == 0
    assert report.profiles_linked == 1

    shadow = (
        await db.execute(select(ShadowUser).where(ShadowUser.email == "cafe@t.ru"))
    ).scalar_one()
    assert shadow.hub_role == "viewer"
    profile = (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "cafe@t.ru")
        )
    ).scalar_one_or_none()
    assert profile is None  # карточки не было — и не появилось

    await db.refresh(prepared)
    assert str(prepared.employee_id) == rows[1]["employee_id"]
    assert prepared.last_activity_at is None


async def test_inactive_account_gets_shadow_but_no_profile(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Требование 2 auth: деактивированный (учётка жива, вход закрыт) не
    получает карточку — иначе членство в аудиториях и письма про курсы."""
    row = _staff_row(tenant_id, email="blocked@t.ru", is_active=False)
    _mock_fetch(monkeypatch, [row])
    report = await sync_staff()
    assert report.inactive_skipped == 1
    assert report.profiles_created == 0

    shadow = (
        await db.execute(select(ShadowUser).where(ShadowUser.email == "blocked@t.ru"))
    ).scalar_one()
    assert shadow.auth_active is False
    profile = (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "blocked@t.ru")
        )
    ).scalar_one_or_none()
    assert profile is None


async def test_role_sweep_clears_stale_and_keeps_current(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Требование 4 auth: отзыва роли в фиде нет — человек просто исчезает
    из выгрузки, и кеш hub_role гасится sweep'ом; строки текущего прогона
    sweep не задевает."""
    stale_eid = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=stale_eid,
            tenant_id=tenant_id,
            email="stale@t.ru",
            full_name="Роль отозвана",
            hub_role="member",
        )
    )
    await db.commit()

    current = _staff_row(tenant_id, email="current@t.ru", role="member")
    _mock_fetch(monkeypatch, [current])
    report = await sync_staff()
    # >=: тенант в тестах общий, sweep честно гасит и тени прошлых тестов.
    assert report.roles_cleared >= 1

    stale = await db.get(ShadowUser, stale_eid)
    await db.refresh(stale)
    assert stale.hub_role is None
    fresh = (
        await db.execute(select(ShadowUser).where(ShadowUser.email == "current@t.ru"))
    ).scalar_one()
    assert fresh.hub_role == "member"


async def test_dry_run_counts_without_writing(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Dry-run отдаёт честные «сделал бы» и не пишет НИЧЕГО: ни тени, ни
    карточки, ни снапшота приглашений, ни sweep'а ролей (и, следовательно,
    ни одного пуша — классификация read-only)."""
    stale_eid = uuid.uuid4()
    db.add(
        ShadowUser(
            employee_id=stale_eid,
            tenant_id=tenant_id,
            email="stale-dry@t.ru",
            full_name="Не должен погаснуть",
            hub_role="member",
        )
    )
    await db.commit()

    rows = [
        _staff_row(tenant_id, email="dry-new@t.ru"),
        {
            "kind": "invitation",
            "invitation_id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "email": "dry-inv@t.ru",
            "role": "member",
        },
    ]
    _mock_fetch(monkeypatch, rows)
    report = await sync_staff(dry_run=True)
    assert report.dry_run is True
    assert report.profiles_created == 1  # «создал бы»
    assert report.invitations == 1
    assert report.roles_cleared == 0

    assert (
        await db.execute(select(ShadowUser).where(ShadowUser.email == "dry-new@t.ru"))
    ).scalar_one_or_none() is None
    assert (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.email == "dry-new@t.ru")
        )
    ).scalar_one_or_none() is None
    assert (
        await db.execute(
            select(AuthInvitation).where(AuthInvitation.email == "dry-inv@t.ru")
        )
    ).scalar_one_or_none() is None
    stale = await db.get(ShadowUser, stale_eid)
    await db.refresh(stale)
    assert stale.hub_role == "member"  # sweep в dry-run не бежит


def _mock_transport(monkeypatch, handler) -> None:
    """Подсовывает httpx.MockTransport в клиент _fetch_staff_pages
    (respx в зависимостях нет, транспорт — штатный мок httpx)."""
    real_client = httpx.AsyncClient

    def make_client(**kw):
        kw.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(staff_sync.httpx, "AsyncClient", make_client)
    monkeypatch.setattr(
        staff_sync,
        "get_settings",
        lambda: SimpleNamespace(
            staff_service_key="svc_test",
            signaris_auth_base_url="https://auth.test",
        ),
    )


async def test_fetch_follows_cursor_and_stops_only_on_null(monkeypatch):
    """Выход из пагинации ТОЛЬКО по next_after=null: страница короче лимита
    концом не является (добивается через границу фаз сотрудники→приглашения)."""
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        calls.append(after or None)
        if not after:
            # 1 строка при limit=200 — «короткая», но next_after есть.
            return httpx.Response(
                200,
                json={"items": [{"kind": "employee"}], "next_after": "e:x"},
            )
        return httpx.Response(
            200, json={"items": [{"kind": "invitation"}], "next_after": None}
        )

    _mock_transport(monkeypatch, handler)
    items = await staff_sync._fetch_staff_pages()
    assert items is not None and len(items) == 2
    assert calls == [None, "e:x"]


async def test_fetch_no_access_is_quiet_none(monkeypatch):
    """401/403 = «доступа пока нет» (не тот ключ / нет скоупа) → None без
    исключения — та же деградация, что 404 (требование 5 auth)."""
    _mock_transport(monkeypatch, lambda request: httpx.Response(403))
    assert await staff_sync._fetch_staff_pages() is None


async def test_fetch_pagination_overflow_returns_none(monkeypatch):
    """Курсор перестал двигаться → предел страниц → None, а НЕ частичный
    снимок (требование 6; на частичном снимке нельзя гасить роли)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": [{"kind": "employee"}], "next_after": "e:loop"}
        )

    _mock_transport(monkeypatch, handler)
    monkeypatch.setattr(staff_sync, "_MAX_PAGES", 3)
    assert await staff_sync._fetch_staff_pages() is None
