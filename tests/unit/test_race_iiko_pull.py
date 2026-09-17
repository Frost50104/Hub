"""Выгрузка чеков для «Гусиной гонки» и fenced-лок слота iiko — без живого сервера.

Цена ошибки: лишняя сессия iiko = занятый слот лицензии сети (общий с Listen),
а неверное тело OLAP = пустая доска, неотличимая от «продаж не было».
"""

from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import httpx
import pytest

from app.services.iiko import service
from app.services.iiko.client import IikoClient
from app.services.iiko.reports import (
    RACE_SALES,
    VERIFIED,
    fetch_race_daily,
    parse_daily_rows,
    validate_fields,
)


def _client(handler) -> IikoClient:
    return IikoClient(
        base_url="https://iiko.test",
        login="API",
        password="secret",
        transport=httpx.MockTransport(handler),
    )


async def test_race_olap_body_shape_and_exclusive_end():
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, text="TOK")
        if req.url.path.endswith("/olap"):
            bodies.append(json.loads(req.content))
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, text="ok")

    async with _client(handler) as c:
        await fetch_race_daily(c, date_from=date(2026, 9, 14), date_to=date(2026, 9, 20))

    assert len(bodies) == 1, "один OLAP-вызов на всю сеть"
    body = bodies[0]
    assert body["reportType"] == "SALES"
    assert body["groupByRowFields"] == ["Department.Id", "OpenDate.Typed"]
    assert body["aggregateFields"] == ["DishAmountInt", "UniqOrderId.OrdersCount"]
    assert body["filters"]["DishType"] == {
        "filterType": "IncludeValues",
        "values": ["GOODS", "DISH"],
    }, "модификаторы позициями не считаются"
    period = body["filters"]["OpenDate.Typed"]
    assert (period["from"], period["to"]) == ("2026-09-14", "2026-09-21"), "to эксклюзивна"


def test_race_fields_are_verified_so_columns_check_is_not_needed():
    for f in (*RACE_SALES.group_by, *RACE_SALES.aggregate, RACE_SALES.date_field):
        assert f in VERIFIED
    validate_fields(RACE_SALES, {"SomethingElse"})  # не падает


def test_parse_daily_rows_keeps_fractions_skips_junk_and_merges_duplicates():
    rows = [
        {"Department.Id": "dep-a", "OpenDate.Typed": "2026-09-14", "DishAmountInt": 250.3,
         "UniqOrderId.OrdersCount": 100},
        {"Department.Id": "dep-a", "OpenDate.Typed": "2026-09-14", "DishAmountInt": 1.7,
         "UniqOrderId.OrdersCount": 1},
        {"Department.Id": "", "OpenDate.Typed": "2026-09-14", "DishAmountInt": 999,
         "UniqOrderId.OrdersCount": 999},
        {"Department.Id": "dep-b", "OpenDate.Typed": "not-a-date", "DishAmountInt": 5,
         "UniqOrderId.OrdersCount": 2},
        {"Department.Id": "dep-b", "OpenDate.Typed": "2026-09-13T00:00:00", "DishAmountInt": "12",
         "UniqOrderId.OrdersCount": "4"},
    ]
    out = parse_daily_rows(rows)
    assert [(r.department_id, r.day, r.receipts, r.items) for r in out] == [
        ("dep-b", date(2026, 9, 13), 4, 12.0),
        ("dep-a", date(2026, 9, 14), 101, 252.0),
    ]


async def test_session_closes_when_race_pull_fails():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, text="TOK")
        if req.url.path.endswith("/olap"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, text="ok")

    with pytest.raises(Exception):  # noqa: B017 — важен logout, не тип ошибки
        async with _client(handler) as c:
            await fetch_race_daily(c, date_from=date(2026, 9, 14), date_to=date(2026, 9, 14))
    assert any(p.endswith("/logout") for p in calls)


# ─── fenced-лок ─────────────────────────────────────────────────────────────


class _FakeRedis:
    """Ровно то подмножество redis.asyncio, которым пользуется лок."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.ttl[key] = ex
        return True

    async def get(self, key):
        return self.store.get(key)

    async def exists(self, key):
        return int(key in self.store)

    async def delete(self, key):
        return int(self.store.pop(key, None) is not None)

    async def eval(self, script, numkeys, key, token):
        assert "redis.call('get'" in script
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


async def test_lock_is_released_only_by_its_owner():
    r = _FakeRedis()
    tenant = uuid4()
    token = await service.try_acquire(r, tenant)
    assert token is not None
    assert await service.try_acquire(r, tenant) is None, "второй держатель не проходит"
    assert await service.release(r, tenant, "someone-else") is False
    assert service.lock_key(tenant) in r.store, "чужой токен лок не снимает"
    assert await service.release(r, tenant, token) is True
    assert service.lock_key(tenant) not in r.store


async def test_lock_ttl_covers_worst_case_pull():
    r = _FakeRedis()
    tenant = uuid4()
    await service.try_acquire(r, tenant)
    assert r.ttl[service.lock_key(tenant)] >= service.RACE_CLIENT_TIMEOUT_SEC


async def test_session_lock_context_raises_busy_without_waiting_forever(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(service, "get_redis", lambda: r)
    tenant = uuid4()
    await service.try_acquire(r, tenant)  # кто-то держит
    with pytest.raises(service.IikoBusy):
        async with service.iiko_session_lock(tenant, wait_sec=0):
            pass


async def test_session_lock_context_acquires_and_releases(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(service, "get_redis", lambda: r)
    tenant = uuid4()
    async with service.iiko_session_lock(tenant, wait_sec=0):
        assert service.lock_key(tenant) in r.store
    assert service.lock_key(tenant) not in r.store
