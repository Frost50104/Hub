"""Sites-sync (0053): зеркало реестра объектов — replace, сверка total, dry-run.

Фетчер мокается monkeypatch'ем (как в test_staff_sync); HTTP-крайности —
через httpx.MockTransport.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shadow import ShadowSite
from app.services import sites_sync
from app.services.sites_sync import sync_sites

pytestmark = pytest.mark.integration


def _site(tenant_id: uuid.UUID, **kw) -> dict:
    return {
        "site_id": str(kw.pop("site_id", uuid.uuid4())),
        "tenant_id": str(tenant_id),
        "code": kw.pop("code", "П14"),
        "name": kw.pop("name", "Приморская 14"),
        "address": kw.pop("address", "СПб, Приморская 14"),
        "legal_name": kw.pop("legal_name", "ИП Тестова"),
        "inn": kw.pop("inn", "780000000000"),
        "email": None,
        "phone": None,
        "archived_at": kw.pop("archived_at", None),
        "refs": kw.pop("refs", [{"system": "hub", "external_id": str(uuid.uuid4())}]),
        **kw,
    }


def _mock_fetch(monkeypatch, items: list[dict] | None, total: int | None = None):
    payload = None if items is None else (items, total if total is not None else len(items))

    async def fake_fetch():
        return payload

    monkeypatch.setattr(sites_sync, "_fetch_sites", fake_fetch)


async def test_replace_snapshot_and_archived_rows_survive(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Вторая синхронизация заменяет зеркало целиком; архивный объект живёт
    строкой с archived_at (удалений в реестре не существует)."""
    keep = uuid.uuid4()
    _mock_fetch(monkeypatch, [_site(tenant_id, site_id=keep), _site(tenant_id)])
    await db.commit()  # синк работает своими сессиями
    report = await sync_sites()
    assert report.available and report.sites == 2 and not report.total_mismatch

    _mock_fetch(
        monkeypatch,
        [
            _site(
                tenant_id,
                site_id=keep,
                name="Приморская 14 (арх)",
                archived_at="2026-09-01T00:00:00Z",
            )
        ],
    )
    report = await sync_sites()
    assert report.sites == 1 and report.archived_sites == 1

    rows = (await db.execute(select(ShadowSite))).scalars().all()
    assert len(rows) == 1
    assert rows[0].site_id == keep and rows[0].archived_at is not None
    assert rows[0].refs and rows[0].refs[0]["system"] == "hub"


async def test_total_mismatch_leaves_mirror_untouched(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    """Формально валидный, но неполный снимок (total=2, items=1) не применяется:
    пустой ответ при их баге иначе стёр бы зеркало replace-семантикой."""
    _mock_fetch(monkeypatch, [_site(tenant_id, name="Живая строка")])
    await db.commit()
    await sync_sites()

    _mock_fetch(monkeypatch, [_site(tenant_id)], total=2)
    report = await sync_sites()
    assert report.total_mismatch is True and report.sites == 0

    rows = (await db.execute(select(ShadowSite))).scalars().all()
    assert len(rows) == 1 and rows[0].name == "Живая строка"


async def test_dry_run_counts_without_writes(db: AsyncSession, tenant_id: uuid.UUID, monkeypatch):
    marker = uuid.uuid4()
    _mock_fetch(monkeypatch, [_site(tenant_id, site_id=marker)])
    await db.commit()
    report = await sync_sites(dry_run=True)
    assert report.dry_run and report.sites == 1
    assert (await db.get(ShadowSite, marker)) is None


async def test_unavailable_is_noop(db: AsyncSession, tenant_id: uuid.UUID, monkeypatch):
    _mock_fetch(monkeypatch, None)
    report = await sync_sites()
    assert report.available is False and report.sites == 0


# Оригинал фиксируем на импорте: повторный _mock_transport в одном тесте иначе
# оборачивает уже обёрнутый клиент (transport дважды).
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_transport(monkeypatch, handler) -> None:
    def make_client(**kw):
        kw.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(sites_sync.httpx, "AsyncClient", make_client)
    monkeypatch.setattr(
        sites_sync,
        "get_settings",
        lambda: SimpleNamespace(
            staff_service_key="svc_test",
            signaris_auth_base_url="https://auth.test",
        ),
    )


async def test_fetch_sends_no_pagination_params(monkeypatch):
    """Контракт: снимок всегда полный, limit/after не шлём и цикла нет."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"total": 1, "items": [{"site_id": "x"}]})

    _mock_transport(monkeypatch, handler)
    fetched = await sites_sync._fetch_sites()
    assert fetched is not None and fetched[1] == 1
    assert len(seen) == 1
    params = dict(seen[0].url.params)
    assert params == {"product": "hub"}  # ни limit, ни after


async def test_fetch_403_and_disabled_404_are_quiet_none(monkeypatch):
    _mock_transport(monkeypatch, lambda r: httpx.Response(403))
    assert await sites_sync._fetch_sites() is None

    _mock_transport(
        monkeypatch,
        lambda r: httpx.Response(404, json={"code": "sites_export_disabled"}),
    )
    assert await sites_sync._fetch_sites() is None


async def test_fetch_bare_404_is_none_too(monkeypatch):
    """Голый 404 (в т.ч. с не-JSON телом nginx) → None; отличие — в логе URL."""
    _mock_transport(monkeypatch, lambda r: httpx.Response(404, text="<html>nope</html>"))
    assert await sites_sync._fetch_sites() is None


async def test_trigger_applies_registry_to_own_tenant_and_pending_endpoint(
    rls_enforced,  # noqa: ARG001 — ДО db: сессия обязана жить на app-роли (иначе RLS обойдён)
    db: AsyncSession,
    tenant_id: uuid.UUID,
    monkeypatch,
):
    """Кнопка = джоба: живой прогон создаёт карточку по объекту с iiko-ссылкой,
    объект без ссылки уходит в «ожидающие»."""
    from app.api.sites import list_pending_sites, trigger_sites_sync
    from app.models.org import Store
    from tests.integration.conftest import make_principal
    from tests.integration.test_project_access import _register

    admin = make_principal(tenant_id, email="admin-sites@t.ru", role="admin", tenant_slug="s")
    await _register(db, admin)
    await db.commit()
    with_iiko = _site(
        tenant_id,
        name="Витебский 101",
        code="В101",
        refs=[{"system": "iiko", "external_id": "dep-7"}],
    )
    without = _site(tenant_id, name="Смоленка 35", code="С35", refs=[])
    _mock_fetch(monkeypatch, [with_iiko, without])
    monkeypatch.setattr(
        "app.api.sites.get_settings",
        lambda: SimpleNamespace(sites_sync_enabled=True, sites_snapshot_fresh_days=14),
    )
    out = await trigger_sites_sync(False, admin, db)
    pending = await list_pending_sites(admin, db)
    assert [(p.name, p.reason) for p in pending.items] == [("Смоленка 35", "no_iiko_ref")]
    assert out["applied"] == {"created": 1, "archived": 0, "pending": 1}
    store = (
        await db.execute(select(Store).where(Store.site_id == uuid.UUID(with_iiko["site_id"])))
    ).scalar_one()
    assert store.name == "Витебский 101" and store.code == "В101"
    pending = await list_pending_sites(admin, db)
    assert [(p.name, p.reason) for p in pending.items] == [("Смоленка 35", "no_iiko_ref")]
