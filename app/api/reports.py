"""Отчёты iiko (волна 2 ассистента).

Живут под `/api/ai/`, потому что именно эта локация nginx держит
`proxy_read_timeout 120s`: OLAP за месяц — самый долгий запрос продукта.

Кто что видит (решение владельца 2026-08-20):

- **вся сеть** — hub-admin, publisher+, офис, ТУ и владельцы франчайзи;
- **403** — линейный сотрудник на точке. Выручка и списания сети не входят в
  его работу.

**Сущности точек НЕ связываются.** Отчёт показывает названия точек так, как их
ведёт iiko, и никакого моста к `stores` не строит: сопоставление по имени —
это перевод, который однажды ошибётся и покажет управляющему чужую выручку,
а имя из iiko человек и так узнаёт. Прямое следствие, принятое владельцем:
сузить отчёт до «своих» точек нечем, поэтому владелец франчайзи видит и чужие.

Офис, ТУ и франчайзи приходится разрешать здесь явно: `resolve_scope` заведён
под аналитику по СОТРУДНИКАМ и отдаёт им скоуп по своим людям, а тут вопрос
только «пускать или нет».
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.services import lifecycle
from app.services.content_access import resolve_content_role
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.iiko.reports import REPORT_ORDER, SPECS
from app.services.org_scope import get_profile
from app.services.project_access import is_hub_admin

router = APIRouter(tags=["iiko-reports"])

# Потолок периода. Не косметика: OLAP за год по сети держит слот лицензии
# минутами, а nginx рвёт соединение на 120с — сотрудник увидел бы 504 и не
# понял, собрался отчёт или нет.
MAX_PERIOD_DAYS = 92


# Роли оргструктуры, которым отчёты положены. Линейного сотрудника здесь нет
# намеренно: выручка и списания сети не входят в его работу.
REPORT_ORG_ROLES = frozenset({"office", "tu", "franchisee_owner"})


async def _require_report_access(db: AsyncSession, principal: Principal) -> None:
    """Пустить или отказать. Скоупа по точкам нет — отчёт всегда по сети."""
    role = await resolve_content_role(db, principal)
    if lifecycle.can(role, "publisher") or is_hub_admin(principal):
        return
    profile = await get_profile(db, principal)
    if (
        profile is not None
        and profile.status == "active"
        and profile.org_role in REPORT_ORG_ROLES
    ):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Отчёты iiko доступны офису, территориальным управляющим и "
            "владельцам франчайзи"
        ),
    )


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
    await _require_report_access(db, principal)
    start, end = _period(date_from, date_to)
    try:
        payload = await iiko_service.get_report(
            tenant_id=principal.tenant_id,
            kind=kind,
            date_from=start,
            date_to=end,
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
