"""Реестр объектов (0053): ручной триггер зеркала. НЕ org.py сознательно —
задача auth прямо предостерегает от соседства с веткой rebuild_tenant в
update_store; этот модуль stores не касается вовсе.

Чтение зеркала (GET /learn/sites) приедет выкатом 3 — отдельной ручкой под
_ADMIN: в зеркале ИНН/юрлица/телефоны, а org_snapshot открыт любому
аутентифицированному и кормит пикеры вне админки.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal

from app.config import get_settings
from app.deps import require_auth

router = APIRouter(tags=["learn-sites"])

_ADMIN = require_auth(roles=["admin"])


@router.post("/learn/sites/sync")
async def trigger_sites_sync(
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(_ADMIN),
) -> dict[str, object]:
    """Ручной прогон зеркала реестра — планировщика нет сознательно
    (данные меняются ~4 раза в год; воркер — это поведение в три часа ночи
    без свидетелей).

    Пока `sites_sync_enabled=false`, живой прогон ПРИНУДИТЕЛЬНО становится
    dry-run — флаг выключают ровно на время порядка включения, и обойти его
    одним вызовом нельзя (паттерн staff-sync).
    """
    from app.services.sites_sync import sync_sites

    effective_dry_run = dry_run or not get_settings().sites_sync_enabled
    report = await sync_sites(dry_run=effective_dry_run)
    return {
        "available": report.available,
        "dry_run": report.dry_run,
        "total": report.total,
        "total_mismatch": report.total_mismatch,
        "sites": report.sites,
        "archived_sites": report.archived_sites,
        "busy_tenants": report.busy_tenants,
        "tenants": len(report.tenants),
    }
