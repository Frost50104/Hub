"""Отчёты iiko: конфиг, кэш и дисциплина лицензионного слота.

Слот лицензии iiko — общий на всю сеть, а не на пользователя. Персональный
`enforce_rate_limit` бьёт по `employee_id` и от этого не защищает: десять
управляющих в обед откроют десять сессий и выведут из строя кассы. Поэтому:

- **кэш на 15 минут** по (тенант, отчёт, период, точка) — повторный вопрос
  того же отчёта не идёт в iiko вовсе;
- **лок per-tenant** — одновременно живёт максимум одна сессия к iiko;
  не дождавшийся получает честное «отчёт уже собирается», а не вторую сессию.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any
from uuid import UUID

import structlog

from app.config import get_settings
from app.redis_client import get_redis
from app.services.iiko.client import IikoClient, IikoError, IikoNotConfigured
from app.services.iiko.reports import fetch_report

log = structlog.get_logger("iiko.service")

LOCK_TTL_SEC = 90
LOCK_WAIT_SEC = 12.0
_LOCK_POLL_SEC = 0.5


class IikoBusy(RuntimeError):
    """Слот занят соседним запросом — повторить через минуту."""


def is_configured() -> bool:
    s = get_settings()
    return bool(s.iiko_base_url and s.iiko_login and s.iiko_password)


def _client() -> IikoClient:
    s = get_settings()
    if not is_configured():
        raise IikoNotConfigured(
            "Отчёты iiko не подключены: задайте SIGNARIS_HUB_IIKO_BASE_URL, "
            "_LOGIN и _PASSWORD"
        )
    return IikoClient(
        base_url=s.iiko_base_url or "",
        login=s.iiko_login or "",
        password=s.iiko_password or "",
        verify_ssl=s.iiko_verify_ssl,
        timeout=s.iiko_timeout_sec,
    )


def _cache_key(
    tenant_id: UUID,
    kind: str,
    date_from: date,
    date_to: date,
    departments: list[str] | None,
) -> str:
    # Скоуп в ключе ОБЯЗАТЕЛЕН и сортируется: иначе ТУ прочитал бы из кэша
    # сетевой отчёт, собранный админом, и увидел бы чужие точки.
    scope = ",".join(sorted(departments)) if departments else "*"
    return f"iiko:report:{tenant_id}:{kind}:{date_from}:{date_to}:{scope}"


async def get_report(
    *,
    tenant_id: UUID,
    kind: str,
    date_from: date,
    date_to: date,
    departments: list[str] | None = None,
    scope_label: str | None = None,
) -> dict[str, Any]:
    redis = get_redis()
    key = _cache_key(tenant_id, kind, date_from, date_to, departments)
    cached = await redis.get(key)
    if cached:
        payload = json.loads(cached)
        payload["cached"] = True
        return payload

    lock_key = f"iiko:lock:{tenant_id}"
    got = await redis.set(lock_key, b"1", nx=True, ex=LOCK_TTL_SEC)
    if not got:
        # Ждём соседа: он, скорее всего, кладёт в кэш ровно то, что нужно нам.
        waited = 0.0
        while waited < LOCK_WAIT_SEC:
            await asyncio.sleep(_LOCK_POLL_SEC)
            waited += _LOCK_POLL_SEC
            cached = await redis.get(key)
            if cached:
                payload = json.loads(cached)
                payload["cached"] = True
                return payload
            if not await redis.exists(lock_key):
                got = await redis.set(lock_key, b"1", nx=True, ex=LOCK_TTL_SEC)
                if got:
                    break
        if not got:
            raise IikoBusy(
                "Отчёт уже собирается по другому запросу — подождите минуту и повторите"
            )

    try:
        async with _client() as client:
            payload = await fetch_report(
                client,
                kind,
                date_from=date_from,
                date_to=date_to,
                departments=departments,
                scope_label=scope_label,
            )
        await redis.set(
            key, json.dumps(payload, ensure_ascii=False), ex=get_settings().iiko_cache_ttl_sec
        )
        payload["cached"] = False
        return payload
    except IikoError:
        raise
    finally:
        await redis.delete(lock_key)


def to_csv(payload: dict[str, Any]) -> str:
    """CSV отчёта. Разделитель — точка с запятой, BOM добавляет ручка: Excel
    в русской локали иначе кладёт всю строку в одну ячейку."""
    lines: list[str] = [f"{payload['title']};{payload['subtitle']}", ""]
    if payload.get("stats"):
        lines.append("Показатель;Значение")
        lines += [f"{s['label']};{s['value']}" for s in payload["stats"]]
        lines.append("")
    if payload.get("bars"):
        lines.append("Название;Значение;К прошлому периоду")
        lines += [f"{b['name']};{b['sum']};{b['delta']}" for b in payload["bars"]]
        lines.append("")
    if payload.get("hours"):
        lines.append("Час;Доля от пика, %")
        lines += [f"{h['label']};{h['pct']}" for h in payload["hours"]]
        lines.append("")
    for block, title in (("top", "Топ продаж"), ("anti", "Тянут вниз")):
        if payload.get(block):
            lines.append(title)
            lines.append("Позиция;Количество;Доля")
            lines += [f"{i['name']};{i['qty']};{i['share']}" for i in payload[block]]
            lines.append("")
    return "\r\n".join(lines)
