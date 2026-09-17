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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import structlog

from app.config import get_settings
from app.redis_client import get_redis
from app.services.iiko.client import IikoClient, IikoError, IikoNotConfigured
from app.services.iiko.reports import fetch_report

log = structlog.get_logger("iiko.service")

# TTL больше худшего OLAP-вызова (race-клиент ждёт до 120 с): истёкший лок у
# живого держателя = вторая сессия на общий слот сети.
LOCK_TTL_SEC = 300
LOCK_WAIT_SEC = 12.0
_LOCK_POLL_SEC = 0.5
# Клиент гонки: `Department.Id × день` — до 63×14 групп на вызов против 63 у
# отчётов; дефолтных 30 с не хватает.
RACE_CLIENT_TIMEOUT_SEC = 120.0

# Fenced-лок: значение — токен держателя, снятие — только своим токеном
# (Lua CAS, как в worker_supervisor). Безусловный DELETE снимал бы ЧУЖОЙ лок,
# если наш TTL истёк, и на слот лицензии открывались бы параллельные сессии.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


class IikoBusy(RuntimeError):
    """Слот занят соседним запросом — повторить через минуту."""


def is_configured() -> bool:
    s = get_settings()
    return bool(s.iiko_base_url and s.iiko_login and s.iiko_password)


def _client(*, timeout: float | None = None) -> IikoClient:
    s = get_settings()
    if not is_configured():
        raise IikoNotConfigured(
            "Отчёты iiko не подключены: задайте SIGNARIS_HUB_IIKO_BASE_URL, _LOGIN и _PASSWORD"
        )
    return IikoClient(
        base_url=s.iiko_base_url or "",
        login=s.iiko_login or "",
        password=s.iiko_password or "",
        verify_ssl=s.iiko_verify_ssl,
        timeout=timeout if timeout is not None else s.iiko_timeout_sec,
    )


def race_client() -> IikoClient:
    return _client(timeout=RACE_CLIENT_TIMEOUT_SEC)


def lock_key(tenant_id: UUID) -> str:
    return f"iiko:lock:{tenant_id}"


async def try_acquire(redis: Any, tenant_id: UUID, *, ttl_sec: int = LOCK_TTL_SEC) -> str | None:
    """Взять per-tenant лок; вернуть токен держателя или None."""
    token = uuid4().hex
    got = await redis.set(lock_key(tenant_id), token, nx=True, ex=ttl_sec)
    return token if got else None


async def release(redis: Any, tenant_id: UUID, token: str) -> bool:
    """Снять лок, только если он всё ещё наш."""
    return bool(await redis.eval(_RELEASE_LUA, 1, lock_key(tenant_id), token))


@asynccontextmanager
async def iiko_session_lock(
    tenant_id: UUID, *, wait_sec: float = LOCK_WAIT_SEC
) -> AsyncIterator[None]:
    """Лок на ОДНУ сессию iiko (один OLAP-вызов): джобы гонки держат его
    коротко и по очереди, не поверх записи в БД."""
    redis = get_redis()
    token = await try_acquire(redis, tenant_id)
    waited = 0.0
    while token is None:
        if waited >= wait_sec:
            raise IikoBusy("Слот iiko занят другим запросом — повторите через минуту")
        await asyncio.sleep(_LOCK_POLL_SEC)
        waited += _LOCK_POLL_SEC
        token = await try_acquire(redis, tenant_id)
    try:
        yield
    finally:
        await release(redis, tenant_id, token)


def _cache_key(
    tenant_id: UUID, kind: str, date_from: date, date_to: date, scope_key: str = ""
) -> str:
    # Скоуп ОБЯЗАН быть в ключе: без него франчайзи получил бы закэшированный
    # полный отчёт сети (и наоборот). Пустой scope_key оставляет прежние
    # ключи — кэш полного отчёта не инвалидируется зря.
    base = f"iiko:report:{tenant_id}:{kind}:{date_from}:{date_to}"
    return f"{base}:scope:{scope_key}" if scope_key else base


async def get_report(
    *,
    tenant_id: UUID,
    kind: str,
    date_from: date,
    date_to: date,
    extra_filters: dict[str, Any] | None = None,
    scope_key: str = "",
) -> dict[str, Any]:
    redis = get_redis()
    key = _cache_key(tenant_id, kind, date_from, date_to, scope_key)
    cached = await redis.get(key)
    if cached:
        payload = json.loads(cached)
        payload["cached"] = True
        return payload

    token = await try_acquire(redis, tenant_id)
    if token is None:
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
            token = await try_acquire(redis, tenant_id)
            if token is not None:
                break
        if token is None:
            raise IikoBusy("Отчёт уже собирается по другому запросу — подождите минуту и повторите")

    try:
        async with _client() as client:
            payload = await fetch_report(
                client,
                kind,
                date_from=date_from,
                date_to=date_to,
                extra_filters=extra_filters,
            )
        await redis.set(
            key, json.dumps(payload, ensure_ascii=False), ex=get_settings().iiko_cache_ttl_sec
        )
        payload["cached"] = False
        return payload
    except IikoError:
        raise
    finally:
        await release(redis, tenant_id, token)


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
