"""Применение снимка реестра объектов к `stores` (решение владельца 19.09).

Реестр auth — источник истины про точки: там закрывают и открывают. Этот
модуль переводит снимок зеркала (`shadow_sites`) в действия над карточками
магазинов Hub. Он сознательно отделён от `sites_sync.py`: тот остаётся чистым
зеркалом (обещание auth «модуль зеркала не касается stores» держится за
файл), а запись в `stores` живёт здесь и зовётся ПОСЛЕ commit'а снимка.

Правила (`plan_apply` — чистая функция под юнит-тестами):
- объект с магазином (любым, даже архивным) → создание никогда; если объект
  архивен, а магазин жив → магазин архивируется (`reason=registry`).
  Правило АСИММЕТРИЧНОЕ: разархивация — только руками, иначе админ Hub и
  реестр перетягивали бы карточку друг у друга;
- живой объект без магазина: без iiko-ссылки — не точка, а строка реестра →
  в «ожидающие» (решает человек); с iiko-ссылкой — карточка создаётся сама,
  КРОМЕ стоп-правила: непривязанная живая карточка с тем же кодом или тем же
  нормализованным именем → в «ожидающие» с кандидатом на привязку (в сторону
  «не создать дубль»: худший случай — объект ждёт админа);
- архивный объект без магазина — ничего.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Store
from app.models.shadow import ShadowSite
from app.services import audit
from app.services.audience_resolver import rebuild_tenant
from app.services.learn_notify import notify_new_audience_members

log = structlog.get_logger("registry_apply")

PendingReason = Literal["no_iiko_ref", "code_collision", "name_collision"]


@dataclass(frozen=True)
class SiteRow:
    site_id: UUID
    code: str | None
    name: str
    address: str | None
    archived_at: datetime | None
    iiko_ref: str | None


@dataclass(frozen=True)
class StoreRow:
    id: UUID
    name: str
    code: str | None
    site_id: UUID | None
    archived_at: datetime | None


@dataclass(frozen=True)
class PendingSite:
    site: SiteRow
    reason: PendingReason
    candidate_store_id: UUID | None = None


@dataclass
class ApplyPlan:
    create: list[SiteRow] = field(default_factory=list)
    archive: list[tuple[StoreRow, SiteRow]] = field(default_factory=list)
    pending: list[PendingSite] = field(default_factory=list)


@dataclass
class ApplyReport:
    created: list[UUID] = field(default_factory=list)
    archived: list[UUID] = field(default_factory=list)
    pending: int = 0


def norm_name(s: str) -> str:
    """Имя для стоп-правила: регистр, ё, пунктуация и пробелы не считаются."""
    return " ".join(re.sub(r"[^\w\s]", " ", s.casefold().replace("ё", "е")).split())


def iiko_ref(refs: list[dict[str, Any]] | None) -> str | None:
    for r in refs or []:
        if r.get("system") == "iiko" and r.get("external_id"):
            return str(r["external_id"])
    return None


def plan_apply(sites: list[SiteRow], stores: list[StoreRow]) -> ApplyPlan:
    plan = ApplyPlan()
    linked: dict[UUID, list[StoreRow]] = {}
    for st in stores:
        if st.site_id is not None:
            linked.setdefault(st.site_id, []).append(st)
    free_live = [st for st in stores if st.site_id is None and st.archived_at is None]
    by_code = {st.code.casefold(): st for st in free_live if st.code}
    by_name = {norm_name(st.name): st for st in free_live}
    for site in sorted(sites, key=lambda s: s.name.casefold()):
        owners = linked.get(site.site_id)
        if owners:
            if site.archived_at is not None:
                plan.archive.extend((st, site) for st in owners if st.archived_at is None)
            continue
        if site.archived_at is not None:
            continue
        if site.iiko_ref is None:
            plan.pending.append(PendingSite(site, "no_iiko_ref"))
            continue
        twin = by_code.get(site.code.casefold()) if site.code else None
        if twin is not None:
            plan.pending.append(PendingSite(site, "code_collision", twin.id))
            continue
        twin = by_name.get(norm_name(site.name))
        if twin is not None:
            plan.pending.append(PendingSite(site, "name_collision", twin.id))
            continue
        plan.create.append(site)
    return plan


def _site_row(s: ShadowSite) -> SiteRow:
    return SiteRow(
        site_id=s.site_id,
        code=s.code,
        name=s.name,
        address=s.address,
        archived_at=s.archived_at,
        iiko_ref=iiko_ref(s.refs),
    )


def _store_row(st: Store) -> StoreRow:
    return StoreRow(
        id=st.id, name=st.name, code=st.code, site_id=st.site_id, archived_at=st.archived_at
    )


async def _load_plan(session: AsyncSession) -> tuple[ApplyPlan, dict[UUID, Store]]:
    # Тенант скоупит RLS сессии — ручного WHERE tenant_id нет по инварианту.
    sites = list((await session.execute(select(ShadowSite))).scalars())
    stores = list((await session.execute(select(Store))).scalars())
    plan = plan_apply([_site_row(s) for s in sites], [_store_row(st) for st in stores])
    return plan, {st.id: st for st in stores}


async def pending_sites(session: AsyncSession) -> list[PendingSite]:
    plan, _ = await _load_plan(session)
    return plan.pending


async def apply_registry(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    dry_run: bool = False,
    actor_id: UUID | None = None,
) -> ApplyReport:
    """Один прогон по тенанту: создать карточки, заархивировать закрытые.

    Идемпотентно: повторный прогон по тому же снимку даёт пустой план.
    Commit — на вызывающем. При хотя бы одном архиве пересчитываются
    аудитории и уходят уведомления новым членам — та же побочка, что у
    ручного архива в `update_store`, и отозвать её нельзя.
    """
    plan, stores = await _load_plan(session)
    report = ApplyReport(pending=len(plan.pending))
    if dry_run:
        report.created = [s.site_id for s in plan.create]
        report.archived = [st.id for st, _ in plan.archive]
        return report
    now = datetime.now(UTC)
    for site in plan.create:
        store = Store(
            tenant_id=tenant_id,
            name=site.name[:255],
            code=(site.code or None) and site.code[:32],
            address=site.address,
            site_id=site.site_id,
        )
        session.add(store)
        await session.flush()
        audit.record(
            session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="create",
            object_type="store",
            object_id=store.id,
            object_label=store.name,
            diff={"source": {"old": None, "new": "registry"}},
        )
        report.created.append(store.id)
    for st_row, site in plan.archive:
        store = stores[st_row.id]
        store.archived_at = now
        audit.record(
            session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="archive",
            object_type="store",
            object_id=store.id,
            object_label=store.name,
            diff={
                "archived": {"old": False, "new": True},
                "reason": {"old": None, "new": "registry"},
                "site_id": {"old": str(site.site_id), "new": str(site.site_id)},
            },
        )
        report.archived.append(store.id)
    await session.flush()
    if report.archived:
        # Магазин участвует в атрибутах его сотрудников (аудитории по точкам).
        diffs = await rebuild_tenant(session, tenant_id)
        await notify_new_audience_members(session, diffs)
    log.info(
        "registry_apply.applied",
        tenant_id=str(tenant_id),
        created=len(report.created),
        archived=len(report.archived),
        pending=report.pending,
    )
    return report
