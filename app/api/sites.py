"""Реестр объектов (0053): ручной триггер зеркала и его чтение. НЕ org.py
сознательно — задача auth прямо предостерегает от соседства с веткой
rebuild_tenant в update_store; этот модуль stores не касается вовсе.

Чтение — СТРОГО _ADMIN: в зеркале ИНН/юрлица/телефоны точек, а org_snapshot
открыт любому аутентифицированному и кормит пикеры вне админки — класть
данные реестра туда нельзя.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_db, require_auth
from app.models.org import Store
from app.models.shadow import ShadowSite
from app.schemas.site import (
    PendingSiteOut,
    PendingSitesResponse,
    SiteMirrorResponse,
    SitesResponse,
)
from app.services.registry_apply import apply_registry, pending_sites

router = APIRouter(tags=["learn-sites"])

_ADMIN = require_auth(roles=["admin"])


def sites_snapshot_fresh(last_synced_at: datetime | None, *, now: datetime, days: int) -> bool:
    """Снимок реестра живой = не старше ФИКСИРОВАННЫХ суток.

    Не «2×интервал» (образец staff_snapshot_fresh): интервала не существует —
    планировщика нет, синк ручной. Протухший снимок откатывает карточки к
    локальным полям с меткой — иначе тихо протухший ключ (403 у нас INFO)
    дал бы пустой адрес там, где раньше был локальный, без единого сигнала."""
    if last_synced_at is None:
        return False
    return (now - last_synced_at).total_seconds() <= days * 86400


@router.get("/learn/sites", response_model=SitesResponse)
async def list_sites(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> SitesResponse:
    """Зеркало реестра текущего тенанта (RLS скоупит сам)."""
    rows = (await db.execute(select(ShadowSite).order_by(ShadowSite.name))).scalars().all()
    last = (await db.execute(select(func.max(ShadowSite.synced_at)))).scalar_one_or_none()
    return SitesResponse(
        items=[SiteMirrorResponse.model_validate(r) for r in rows],
        snapshot_fresh=sites_snapshot_fresh(
            last,
            now=datetime.now(UTC),
            days=get_settings().sites_snapshot_fresh_days,
        ),
    )


@router.post("/learn/sites/sync")
async def trigger_sites_sync(
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Ручной прогон зеркала реестра + применение к магазинам своего
    тенанта — то же, что часовая джоба `app/jobs/sites_sync.py` (с 19.09
    планировщик есть: реестр — источник истины про точки).

    Пока `sites_sync_enabled=false`, живой прогон ПРИНУДИТЕЛЬНО становится
    dry-run — флаг выключают ровно на время порядка включения, и обойти его
    одним вызовом нельзя (паттерн staff-sync).
    """
    from app.services.sites_sync import sync_sites

    effective_dry_run = dry_run or not get_settings().sites_sync_enabled
    report = await sync_sites(dry_run=effective_dry_run)
    applied: dict[str, int] | None = None
    if (
        not effective_dry_run
        and report.available
        and not report.total_mismatch
        and str(principal.tenant_id) not in report.busy
    ):
        rep = await apply_registry(db, principal.tenant_id, actor_id=principal.employee_id)
        await db.commit()
        applied = {
            "created": len(rep.created),
            "archived": len(rep.archived),
            "pending": rep.pending,
        }
    return {
        "available": report.available,
        "dry_run": report.dry_run,
        "total": report.total,
        "total_mismatch": report.total_mismatch,
        "sites": report.sites,
        "archived_sites": report.archived_sites,
        "busy_tenants": report.busy_tenants,
        "tenants": len(report.tenants),
        "applied": applied,
    }


@router.get("/learn/sites/pending", response_model=PendingSitesResponse)
async def list_pending_sites(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> PendingSitesResponse:
    """Объекты реестра без карточки, которые автоматика не завела сама."""
    items = await pending_sites(db)
    ids = [p.candidate_store_id for p in items if p.candidate_store_id is not None]
    names = (
        dict((await db.execute(select(Store.id, Store.name).where(Store.id.in_(ids)))).all())
        if ids
        else {}
    )
    return PendingSitesResponse(
        items=[
            PendingSiteOut(
                site_id=p.site.site_id,
                code=p.site.code,
                name=p.site.name,
                address=p.site.address,
                iiko_ref=p.site.iiko_ref,
                reason=p.reason,
                candidate_store_id=p.candidate_store_id,
                candidate_store_name=names.get(p.candidate_store_id),
            )
            for p in items
        ]
    )
