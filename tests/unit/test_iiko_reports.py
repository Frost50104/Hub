"""Клиент и пресеты iiko (волна 2 ассистента) — без живого сервера.

Что здесь важно проверить, потому что цена ошибки высокая:
- сессия ЗАКРЫВАЕТСЯ при любом исходе (каждая занимает слот лицензии сети);
- `to` в фильтре периода эксклюзивна (иначе отчёт «за 18-е» приходит пустым,
  а пустой отчёт на экране неотличим от «продаж не было»);
- падение выручки НЕ красится как ошибка;
- непроверенные имена полей ловятся сверкой с /columns.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.services.iiko.client import IikoAuthError, IikoClient, IikoError
from app.services.iiko.reports import (
    SPECS,
    build_payload,
    fetch_report,
    fmt_delta,
    fmt_period,
    validate_fields,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def _client(handler, **kw) -> IikoClient:
    return IikoClient(
        base_url="https://iiko.test",
        login="API",
        password="secret",
        transport=_transport(handler),
        **kw,
    )


async def test_session_closes_even_when_olap_fails():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, text='"TOKEN"')
        if req.url.path.endswith("/olap"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, text="ok")

    with pytest.raises(IikoError):
        async with _client(handler) as c:
            await c.olap(
                report_type="SALES",
                date_from=date(2026, 8, 18),
                date_to=date(2026, 8, 18),
                group_by=["Department"],
                aggregate=["DishDiscountSumInt"],
            )
    assert any(p.endswith("/logout") for p in calls), "слот лицензии не освобождён"


async def test_bad_password_is_its_own_error():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth"):
            return httpx.Response(401, text="Неверный пароль для пользователя 'API'")
        return httpx.Response(200, text="ok")

    with pytest.raises(IikoAuthError):
        async with _client(handler):
            pass


async def test_period_end_is_exclusive_for_iiko():
    """«Отчёт за 18 августа» уходит в iiko как from=18, to=19."""
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, text="TOK")
        if req.url.path.endswith("/olap"):
            import json

            seen.update(json.loads(req.content))
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, text="ok")

    async with _client(handler) as c:
        await c.olap(
            report_type="SALES",
            date_from=date(2026, 8, 18),
            date_to=date(2026, 8, 18),
            group_by=["Department"],
            aggregate=["DishDiscountSumInt"],
        )
    period = seen["filters"]["OpenDate.Typed"]
    assert period["from"] == "2026-08-18"
    assert period["to"] == "2026-08-19", "to должна быть эксклюзивной и больше from"


async def test_revenue_report_shapes_bars_and_delta():
    rows = [
        {"Department": "Галерея", "DishDiscountSumInt": 1_042_300, "UniqOrderId.OrdersCount": 1700},
        {"Department": "Парнас", "DishDiscountSumInt": 584_200, "UniqOrderId.OrdersCount": 900},
    ]
    prev = [
        {"Department": "Галерея", "DishDiscountSumInt": 940_000},
        {"Department": "Парнас", "DishDiscountSumInt": 635_000},
    ]
    p = build_payload(
        "revenue", rows, prev,
        date_from=date(2026, 8, 12), date_to=date(2026, 8, 18), store_filter=None,
    )
    bars = {b["name"]: b for b in p["bars"]}
    assert bars["Галерея"]["pct"] == 100  # самая длинная полоса
    assert bars["Галерея"]["up"] is True
    assert bars["Парнас"]["up"] is False, "падение обязано быть помечено"
    assert "−" in bars["Парнас"]["delta"]
    # Деньги набираются НЕРАЗРЫВНЫМИ пробелами: «1 042 300 ₽» не должно
    # рваться по строкам ни в плашке, ни в полосе.
    assert p["stats"][0]["value"] == "1,63\u00a0млн\u00a0₽"
    assert "\u00a0" in bars["Галерея"]["sum"]
    assert " " not in bars["Галерея"]["sum"].replace("\u00a0", "")
    assert "Парнас" in (p["note"] or "")


async def test_empty_report_is_not_a_crash():
    p = build_payload(
        "revenue", [], [],
        date_from=date(2026, 8, 12), date_to=date(2026, 8, 18), store_filter=None,
    )
    assert p["bars"] == []
    assert p["stats"][3]["value"] == "—", "нет чеков — прочерк, а не ноль"


def test_delta_without_base_is_neutral():
    assert fmt_delta(100, 0) == ("—", True)
    assert fmt_delta(100, 100) == ("0%", True)
    assert fmt_delta(90, 100)[1] is False


def test_period_label_is_human():
    assert fmt_period(date(2026, 8, 12), date(2026, 8, 18)) == "12–18 августа"
    assert fmt_period(date(2026, 8, 18), date(2026, 8, 18)) == "18 августа"
    assert fmt_period(date(2026, 7, 30), date(2026, 8, 2)) == "30 июля — 2 августа"


def test_unverified_field_fails_loudly():
    """Пустой график хуже внятной ошибки: непроверенные имена полей ловятся
    сверкой с /columns до выгрузки."""
    with pytest.raises(IikoError) as exc:
        validate_fields(SPECS["items"], {"Department", "DishDiscountSumInt"})
    assert "DishName" in str(exc.value)
    # Пустой список колонок не мешает работать — сверка необязательна.
    validate_fields(SPECS["items"], set())


async def test_fetch_report_asks_previous_period_for_delta():
    periods: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, text="TOK")
        if req.url.path.endswith("/columns"):
            return httpx.Response(200, json={"Department": {}, "DishDiscountSumInt": {}})
        if req.url.path.endswith("/olap"):
            import json

            body = json.loads(req.content)
            f = body["filters"]["OpenDate.Typed"]
            periods.append((f["from"], f["to"]))
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, text="ok")

    async with _client(handler) as c:
        await fetch_report(
            c, "revenue", date_from=date(2026, 8, 12), date_to=date(2026, 8, 18)
        )
    assert periods[0] == ("2026-08-12", "2026-08-19")
    # Предыдущий период — ровно такой же длины, встык.
    assert periods[1] == ("2026-08-05", "2026-08-12")
