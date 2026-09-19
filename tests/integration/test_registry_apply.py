"""Реестр auth ведёт `stores` (19.09): создание карточек по живым объектам,
архив по архивным, стоп-правило, ожидающие; ручная привязка через API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.org import create_store, update_store
from app.models.audit import AuditLog
from app.models.org import Store
from app.models.shadow import ShadowSite
from app.schemas.org import StoreCreate, StoreUpdate
from app.services.registry_apply import apply_registry, pending_sites
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


# `registry_apply` читает `Store`/`ShadowSite` без ручного tenant-фильтра —
# под суперюзером тестов он увидел бы магазины соседних тестов.
@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


def _site(tenant_id, name, *, code=None, iiko="dep-9", archived=False):
    return ShadowSite(
        site_id=uuid.uuid4(),
        tenant_id=tenant_id,
        code=code,
        name=name,
        address="СПб, " + name,
        archived_at=datetime.now(UTC) if archived else None,
        refs=[{"system": "iiko", "external_id": iiko}] if iiko else [],
        synced_at=datetime.now(UTC),
    )


async def test_apply_creates_archives_and_reports_pending(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    new = _site(tenant_id, "Витебский 101", code="В101", iiko="dep-7")
    no_ref = _site(tenant_id, "Смоленка 35", iiko=None)
    twin = _site(tenant_id, "Дальняя без реестра", code="Д9", iiko="dep-8")
    db.add_all([new, no_ref, twin])
    # объект точки C закрывается в реестре
    site_c = await db.get(ShadowSite, net.C.site_id)
    site_c.archived_at = datetime.now(UTC)
    await db.flush()

    dry = await apply_registry(db, tenant_id, dry_run=True)
    assert dry.created == [new.site_id] and dry.archived == [net.C.id] and dry.pending == 2
    assert (await db.get(Store, net.C.id)).archived_at is None, "dry-run ничего не пишет"

    rep = await apply_registry(db, tenant_id)
    assert len(rep.created) == 1 and rep.archived == [net.C.id] and rep.pending == 2
    created = await db.get(Store, rep.created[0])
    assert (created.name, created.code, created.site_id, created.address) == (
        "Витебский 101",
        "В101",
        new.site_id,
        "СПб, Витебский 101",
    )
    await db.refresh(net.C)
    assert net.C.archived_at is not None
    reasons = {p.site.site_id: (p.reason, p.candidate_store_id) for p in await pending_sites(db)}
    assert reasons == {
        no_ref.site_id: ("no_iiko_ref", None),
        twin.site_id: ("name_collision", net.D.id),
    }
    entries = (
        await db.execute(
            select(AuditLog.action, AuditLog.object_id, AuditLog.diff).where(
                AuditLog.object_type == "store", AuditLog.actor_id.is_(None)
            )
        )
    ).all()
    assert {(a, o) for a, o, _ in entries} == {("create", created.id), ("archive", net.C.id)}
    assert all(d["reason"]["new"] == "registry" for _, o, d in entries if o == net.C.id)

    again = await apply_registry(db, tenant_id)
    assert not again.created and not again.archived, "идемпотентно"

    # объект снова живой — карточка не воскресает (разархивация только руками)
    site_c.archived_at = None
    await db.flush()
    await apply_registry(db, tenant_id)
    await db.refresh(net.C)
    assert net.C.archived_at is not None


async def test_manual_link_validation(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    free = _site(tenant_id, "Новая точка", code="Н1")
    closed = _site(tenant_id, "Закрытая", archived=True)
    db.add_all([free, closed])
    await db.flush()

    async def link(store_id, site_id):
        return await update_store(store_id, StoreUpdate(site_id=site_id), net.admin, db)

    with pytest.raises(HTTPException) as e:
        await link(net.D.id, net.A.site_id)
    assert e.value.status_code == 409 and "Арсенальная" in e.value.detail
    with pytest.raises(HTTPException) as e:
        await link(net.D.id, closed.site_id)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        await link(net.D.id, uuid.uuid4())
    assert e.value.status_code == 422

    out = await link(net.D.id, free.site_id)
    assert out.site_id == free.site_id
    # тот же объект — второй живой карточке нельзя
    with pytest.raises(HTTPException) as e:
        await create_store(StoreCreate(name="Ещё одна", site_id=free.site_id), net.admin, db)
    assert e.value.status_code == 409
    # отвязать — можно
    out = await link(net.D.id, None)
    assert out.site_id is None
    created = await create_store(StoreCreate(name="Ещё одна", site_id=free.site_id), net.admin, db)
    assert created.site_id == free.site_id


async def test_refresh_follows_registry_for_born_cards_and_only_fills_legacy_address(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    born_site = _site(tenant_id, "Коменданский пр., д.17,", code=None, iiko="dep-7")
    db.add(born_site)
    # бэкфилленная C: имя Hub короткое, в реестре — адресная строка
    site_c = await db.get(ShadowSite, net.C.site_id)
    site_c.name, site_c.address = "Проспект Ветеранов, дом 185", "СПб, Ветеранов 185"
    await db.flush()
    rep = await apply_registry(db, tenant_id)
    born = await db.get(Store, rep.created[0])
    assert (born.registry_name, born.registry_code) == ("Коменданский пр., д.17,", None)
    await db.refresh(net.C)
    assert rep.refreshed == [net.C.id], "у бэкфилленной заполнился только адрес"
    assert (net.C.name, net.C.address) == ("Ветеранов", "СПб, Ветеранов 185")
    assert net.C.registry_name == "Проспект Ветеранов, дом 185"
    # реестр поправил имя и дал код рождённой карточке; C снова переименовали
    born_site.name, born_site.code = "Комендантский пр., д. 17", "К17"
    site_c.name = "пр. Ветеранов, 185"
    await db.flush()
    rep = await apply_registry(db, tenant_id)
    assert rep.refreshed == [born.id] and rep.conflicts == 0
    await db.refresh(born)
    await db.refresh(net.C)
    assert (born.name, born.code, born.registry_code) == ("Комендантский пр., д. 17", "К17", "К17")
    assert net.C.name == "Ветеранов", "имя бэкфилленной карточки не трогаем"
    # ручная правка имени в Hub — реестр больше не переименовывает
    born.name = "Комендантский 17"
    born_site.name = "Комендантский проспект, 17"
    await db.flush()
    await apply_registry(db, tenant_id)
    await db.refresh(born)
    assert born.name == "Комендантский 17"
    assert not (await apply_registry(db, tenant_id)).refreshed, "идемпотентно"


async def test_refresh_name_conflict_is_isolated_by_savepoint(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    born_site = _site(tenant_id, "Новая", code="Н1", iiko="dep-7")
    db.add(born_site)
    await db.flush()
    rep = await apply_registry(db, tenant_id)
    born = await db.get(Store, rep.created[0])
    # реестр переименовал объект в имя ЖИВОЙ карточки D → uq_stores_active_name;
    # одновременно объект C закрывается — архив должен пройти несмотря на конфликт
    born_site.name = net.D.name
    site_c = await db.get(ShadowSite, net.C.site_id)
    site_c.archived_at = datetime.now(UTC)
    await db.flush()
    rep = await apply_registry(db, tenant_id)
    assert rep.conflicts == 1 and rep.archived == [net.C.id] and not rep.refreshed
    await db.refresh(born)
    assert born.name == "Новая"
