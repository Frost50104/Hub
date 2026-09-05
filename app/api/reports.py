"""Отчёты iiko (волна 2 ассистента; скоуп франчайзи — 05.09, выкат 3б).

Живут под `/api/ai/`, потому что именно эта локация nginx держит
`proxy_read_timeout 120s`: OLAP за месяц — самый долгий запрос продукта.

Кто что видит (решение владельца 2026-08-20, дополнено 05.09):

- **вся сеть** — hub-admin, publisher+, офис и ТУ;
- **владелец франчайзи — ТОЛЬКО СВОИ точки** (выкат 3б): фильтр по
  `Department.Id` из реестра объектов (`stores.site_id` → `shadow_sites.refs`
  system=iiko). Связи размечены человеком и подтверждены владельцем по
  таблице выручки 05.09 — блокирующее требование auth выполнено. Моста по
  ИМЕНИ по-прежнему нет (0039): скоуп ключуется на GUID. Допущенный как
  publisher/admin франчайзи остаётся с полной сетью — основание допуска
  решает (`_require_report_access` возвращает его явно);
- **403** — линейный сотрудник на точке.

Следствия скоупа: кэш-ключ отчёта ВКЛЮЧАЕТ скоуп (иначе франчайзи получил бы
закэшированный отчёт сети); ноль привязанных точек — явный отказ, а не пустой
фильтр (пустой IncludeValues = вся сеть); `writeoff` франчайзи недоступен —
TRANSACTIONS-тип не отдаёт `Department.Id` (проверено columns() 05.09), и
фильтровать его нечем.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.org import Store
from app.models.shadow import ShadowSite
from app.services import lifecycle
from app.services.content_access import resolve_content_role
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.iiko.reports import REPORT_ORDER, SPECS
from app.services.org_scope import get_profile, resolve_scope
from app.services.project_access import is_hub_admin

router = APIRouter(tags=["iiko-reports"])

# Потолок периода. Не косметика: OLAP за год по сети держит слот лицензии
# минутами, а nginx рвёт соединение на 120с — сотрудник увидел бы 504 и не
# понял, собрался отчёт или нет.
MAX_PERIOD_DAYS = 92


# Роли оргструктуры, которым отчёты положены. Линейного сотрудника здесь нет
# намеренно: выручка и списания сети не входят в его работу.
REPORT_ORG_ROLES = frozenset({"office", "tu", "franchisee_owner"})


async def _require_report_access(db: AsyncSession, principal: Principal) -> str:
    """Пустить или отказать; вернуть ОСНОВАНИЕ допуска — от него зависит скоуп.

    `"full"` — вся сеть (publisher/hub-admin/офис/ТУ), `"franchisee"` — только
    свои точки. Порядок веток важен: франчайзи с content_role=publisher
    допущен КАК publisher и видит сеть — скоуп не меняет это молча
    (правило показано владельцу вместе с таблицей выручки 05.09)."""
    role = await resolve_content_role(db, principal)
    if lifecycle.can(role, "publisher") or is_hub_admin(principal):
        return "full"
    profile = await get_profile(db, principal)
    if (
        profile is not None
        and profile.status == "active"
        and profile.org_role in REPORT_ORG_ROLES
    ):
        return "franchisee" if profile.org_role == "franchisee_owner" else "full"
    raise HTTPException(
        status_code=403,
        detail=(
            "Отчёты iiko доступны офису, территориальным управляющим и "
            "владельцам франчайзи"
        ),
    )


async def _franchisee_department_ids(db: AsyncSession, principal: Principal) -> list[str]:
    """iiko-подразделения точек франчайзи: свои магазины → site_id → refs.

    `resolve_scope` отдаёт живые магазины по `Store.franchisee_id`; дальше —
    зеркало реестра. Дубли магазинов дают один и тот же Department.Id —
    set() схлопывает."""
    scope = await resolve_scope(db, principal)
    if scope.kind != "stores" or not scope.store_ids:
        return []
    site_ids = [
        sid
        for (sid,) in await db.execute(
            select(Store.site_id).where(
                Store.id.in_(scope.store_ids), Store.site_id.is_not(None)
            )
        )
    ]
    if not site_ids:
        return []
    dept_ids: set[str] = set()
    for (refs,) in await db.execute(
        select(ShadowSite.refs).where(ShadowSite.site_id.in_(site_ids))
    ):
        for ref in refs or []:
            if ref.get("system") == "iiko" and ref.get("external_id"):
                dept_ids.add(str(ref["external_id"]))
    return sorted(dept_ids)


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """По умолчанию — прошлая полная неделя (пн–вс), как в макете."""
    today = datetime.now(UTC).date()
    if date_from is None or date_to is None:
        last_monday = today - timedelta(days=today.weekday() + 7)
        return last_monday, last_monday + timedelta(days=6)
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="Конец периода раньше начала")
    if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Период больше {MAX_PERIOD_DAYS} дней — сузьте запрос",
        )
    return date_from, date_to


@router.get("/ai/reports")
async def list_reports(
    _principal: Principal = Depends(require_auth()),
) -> dict[str, Any]:
    """Список отчётов и признак подключения — фронт рисует вкладки и,
    если не подключено, экран «Ассистент ещё не подключён»."""
    return {
        "configured": iiko_service.is_configured(),
        "reports": [
            {"key": k, "title": SPECS[k].title, "chart": SPECS[k].chart}
            for k in REPORT_ORDER
        ],
    }


async def _build(
    kind: str,
    date_from: date | None,
    date_to: date | None,
    principal: Principal,
    db: AsyncSession,
) -> dict[str, Any]:
    if kind not in SPECS:
        raise HTTPException(status_code=404, detail="Такого отчёта нет")
    # Лимит жёстче обычного: за каждым промахом кэша стоит слот лицензии.
    await enforce_rate_limit(
        bucket="ai:iiko", employee_id=str(principal.employee_id), limit=10, window_sec=60
    )
    basis = await _require_report_access(db, principal)
    extra_filters: dict[str, Any] | None = None
    scope_key = ""
    if basis == "franchisee":
        if kind == "writeoff":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Отчёт по списаниям пока не умеет разбивку по точкам "
                    "(iiko не отдаёт id подразделения в этом типе отчёта) — "
                    "он доступен офису"
                ),
            )
        dept_ids = await _franchisee_department_ids(db, principal)
        if not dept_ids:
            # Пустой IncludeValues означал бы ВСЮ сеть — отказ обязан быть явным.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Точки вашего франчайзи ещё не привязаны к реестру "
                    "объектов — напишите администратору"
                ),
            )
        extra_filters = {
            "Department.Id": {"filterType": "IncludeValues", "values": dept_ids}
        }
        scope_key = hashlib.sha256(",".join(dept_ids).encode()).hexdigest()[:16]
    start, end = _period(date_from, date_to)
    try:
        payload = await iiko_service.get_report(
            tenant_id=principal.tenant_id,
            kind=kind,
            date_from=start,
            date_to=end,
            extra_filters=extra_filters,
            scope_key=scope_key,
        )
    except IikoNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except iiko_service.IikoBusy as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except IikoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None

    return payload


@router.get("/ai/reports/{kind}")
async def get_report(
    kind: str,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _build(kind, date_from, date_to, principal, db)


@router.get("/ai/reports/{kind}/csv")
async def get_report_csv(
    kind: str,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    payload = await _build(kind, date_from, date_to, principal, db)
    body = iiko_service.to_csv(payload)
    filename = f"iiko-{kind}-{payload['period']['from']}_{payload['period']['to']}.csv"
    return Response(
        # BOM обязателен: Excel в русской локали иначе читает файл как
        # cp1251 и кладёт всю строку в одну ячейку.
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
