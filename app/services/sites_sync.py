"""Sites-sync (0053): зеркало реестра объектов auth — `shadow_sites`.

Контракт — docs/handoffs/HUB_TASK_sites_contract.md + _ANSWER (принят auth без
изменений). Ключевые свойства, на которых стоит модуль:

- **Пагинации НЕТ**: ответ всегда полный, `limit`/`after` игнорируются auth.
  Цикла из staff_sync сюда не копировать — неразбитый ответ делает частичный
  снимок невозможным ПО ПОСТРОЕНИЮ, и на этом держится безопасность replace.
- **`len(items) == total` сверяется ДО любых записей**: пустой формально
  валидный ответ (`{"total": 65, "items": []}`) при баге фильтра на стороне
  auth иначе стёр бы зеркало целиком.
- **Replace-семантика безопасна**: архивные объекты ПРИХОДЯТ в снимке с
  `archived_at`, а удаления объектов в реестре не существует вовсе — пропасть
  строка может только вместе с реестром. Тенант, целиком пропавший из ответа,
  НЕ вычищается (подтверждено auth: снимок сообщает состояние, вычистка по
  отсутствию — вывод о событии).
- **Модуль не касается `stores`** — ни импортом, ни запросом (grep — пункт
  приёмки auth). `stores.site_id` пишет только разовый бэкфилл (выкат 2),
  `stores.archived_at` принадлежит Hub и реестр её не отражает.
- Планировщика НЕТ (ручной триггер — POST /api/learn/sites/sync); от гонки
  двух ручных запусков — per-tenant `pg_try_advisory_xact_lock`.
- 401/403 и 404 с телом `{"code": "sites_export_disabled"}` — «доступа/фида
  пока нет», INFO без шторма; ГОЛЫЙ 404 — WARNING с полным URL: он неотличим
  от опечатки в base_url, и без URL зеркало осталось бы пустым молча.

Тело несёт ИНН, юрлица и телефоны точек — в логи только числа и id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import delete, text

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.shadow import ShadowSite

log = structlog.get_logger("sites_sync")


@dataclass
class SitesSyncReport:
    """Счётчики прогона — их возвращает ручной триггер."""

    available: bool = True
    dry_run: bool = False
    total: int = 0
    total_mismatch: bool = False
    sites: int = 0
    archived_sites: int = 0
    busy_tenants: int = 0
    tenants: set[str] = field(default_factory=set)
    # Занятые try-локом тенанты — применение реестра по ним пропускается
    # (план по старому зеркалу был бы планом по прошлому).
    busy: set[str] = field(default_factory=set)


async def _fetch_sites() -> tuple[list[dict[str, Any]], int] | None:
    """Полный снимок реестра; None = снимка нет (нет доступа/фид выключен/сеть).

    Единственная точка HTTP — тесты подменяют её целиком или транспортом.
    """
    settings = get_settings()
    if not settings.staff_service_key:
        log.warning("sites_sync.no_service_key")
        return None
    url = f"{settings.signaris_auth_base_url}/api/products/sites"
    try:
        async with httpx.AsyncClient(
            headers={"X-Service-Key": settings.staff_service_key},
            timeout=20.0,
        ) as client:
            resp = await client.get(url, params={"product": "hub"})
    except httpx.HTTPError as exc:
        log.warning("sites_sync.fetch_failed", error=type(exc).__name__)
        return None
    if resp.status_code in (401, 403):
        log.info("sites_sync.unavailable", status=resp.status_code)
        return None
    if resp.status_code == 404:
        # Машиночитаемый рубильник auth против голого 404: второй неотличим
        # от опечатки в base_url, поэтому обязан кричать WARNING'ом с URL.
        try:
            body_code = resp.json().get("code")
        except ValueError:
            body_code = None
        if body_code == "sites_export_disabled":
            log.info("sites_sync.unavailable", status=404, code=body_code)
        else:
            log.warning("sites_sync.bare_404", url=str(resp.request.url))
        return None
    if resp.status_code != 200:
        log.warning("sites_sync.fetch_failed", status=resp.status_code)
        return None
    data = resp.json()
    items = data.get("items") or []
    total = data.get("total")
    return items, int(total) if total is not None else len(items)


def _rows_by_tenant(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_tenant: dict[str, list[dict[str, Any]]] = {}
    for row in items:
        tenant_id = row.get("tenant_id")
        if tenant_id and row.get("site_id"):
            by_tenant.setdefault(str(tenant_id), []).append(row)
    return by_tenant


async def sync_sites(*, dry_run: bool = False) -> SitesSyncReport:
    """Один прогон: fetch → сверка total → per-tenant replace под try-локом.

    `dry_run=True` — тот же fetch и те же счётчики, ни одной записи.
    """
    report = SitesSyncReport(dry_run=dry_run)
    fetched = await _fetch_sites()
    if fetched is None:
        report.available = False
        return report
    items, total = fetched
    report.total = total
    if len(items) != total:
        # Применять нечего: формально валидный, но неполный снимок стёр бы
        # зеркало replace-семантикой.
        log.error("sites_sync.total_mismatch", total=total, items=len(items))
        report.total_mismatch = True
        return report

    now = datetime.now(UTC)
    for tenant_id, rows in _rows_by_tenant(items).items():
        report.tenants.add(tenant_id)
        async with tenant_scoped_session(UUID(tenant_id)) as db:
            if not dry_run:
                got = (
                    await db.execute(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtextextended(:key, 0))"
                        ),
                        {"key": f"hub_sites_sync:{tenant_id}"},
                    )
                ).scalar_one()
                if not got:
                    log.info("sites_sync.tenant_busy", tenant_id=tenant_id)
                    report.busy_tenants += 1
                    report.busy.add(tenant_id)
                    continue
                # Тенант скоупит RLS сессии — ручной WHERE tenant_id запрещён.
                await db.execute(delete(ShadowSite))
            for row in rows:
                report.sites += 1
                if row.get("archived_at"):
                    report.archived_sites += 1
                if dry_run:
                    continue
                db.add(
                    ShadowSite(
                        site_id=UUID(str(row["site_id"])),
                        tenant_id=UUID(tenant_id),
                        code=row.get("code"),
                        name=str(row.get("name") or "")[:255] or "—",
                        address=row.get("address"),
                        legal_name=(row.get("legal_name") or None),
                        inn=(row.get("inn") or None),
                        email=(row.get("email") or None),
                        phone=(row.get("phone") or None),
                        archived_at=_parse_dt(row.get("archived_at")),
                        refs=row.get("refs") or [],
                        synced_at=now,
                    )
                )
            if not dry_run:
                await db.commit()
    log.info(
        "sites_sync.done",
        dry_run=dry_run,
        total=total,
        tenants=len(report.tenants),
        sites=report.sites,
        archived=report.archived_sites,
        busy=report.busy_tenants,
    )
    return report


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
