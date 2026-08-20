"""Отчёты iiko (волна 2 ассистента).

Живут под `/api/ai/`, потому что именно эта локация nginx держит
`proxy_read_timeout 120s`: OLAP за месяц — самый долгий запрос продукта.

Доступ — тот же гейт, что у learn-аналитики (Ф5): publisher+/hub-admin видят
всю сеть, ТУ и владелец франчайзи — свои точки, линейный сотрудник получает
403. Скоуп выражается через `stores.iiko_department`: в iiko точка
адресуется строкой-именем, и без сопоставления управляющий увидел бы сеть
целиком.
"""

from __future__ import annotations

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
from app.services import lifecycle
from app.services.content_access import resolve_content_role
from app.services.iiko import service as iiko_service
from app.services.iiko.client import IikoError, IikoNotConfigured
from app.services.iiko.reports import REPORT_ORDER, SPECS
from app.services.org_scope import resolve_scope

router = APIRouter(tags=["iiko-reports"])

# Потолок периода. Не косметика: OLAP за год по сети держит слот лицензии
# минутами, а nginx рвёт соединение на 120с — сотрудник увидел бы 504 и не
# понял, собрался отчёт или нет.
MAX_PERIOD_DAYS = 92


async def _departments(
    db: AsyncSession, principal: Principal
) -> tuple[list[str] | None, str | None]:
    """(имена точек в iiko | None=вся сеть, подпись скоупа). 403 линейным."""
    role = await resolve_content_role(db, principal)
    scope = await resolve_scope(db, principal)
    if lifecycle.can(role, "publisher") or scope.kind == "all":
        return None, None
    if scope.kind == "stores":
        rows = (
            await db.execute(
                select(Store.name, Store.iiko_department).where(
                    Store.id.in_(scope.store_ids or frozenset())
                )
            )
        ).all()
        names = [d for _, d in rows if d]
        if not names:
            raise HTTPException(
                status_code=409,
                detail=(
                    "У ваших точек не заполнено соответствие с iiko — "
                    "попросите администратора указать «Торговое предприятие» "
                    "в карточке магазина"
                ),
            )
        label = ", ".join(sorted(n for n, _ in rows))
        return names, (label if len(label) <= 80 else f"{len(names)} точек")
    raise HTTPException(
        status_code=403, detail="Отчёты iiko доступны руководителям и публикаторам"
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
    departments, label = await _departments(db, principal)
    start, end = _period(date_from, date_to)
    try:
        return await iiko_service.get_report(
            tenant_id=principal.tenant_id,
            kind=kind,
            date_from=start,
            date_to=end,
            departments=departments,
            scope_label=label,
        )
    except IikoNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except iiko_service.IikoBusy as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except IikoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


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
