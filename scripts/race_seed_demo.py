#!/usr/bin/env python3
"""Синтетика для «Гусиной гонки» на staging — iiko там недоступен по правилу.

Заполняет `race_daily_stats` правдоподобными числами по всем подразделениям
участников текущего конкурса (или всех привязанных точек) за N дней и, если
конкурс есть, пересчитывает базы из этих же дней (`pull=False`).

    /opt/signaris-hub-staging/.venv/bin/python scripts/race_seed_demo.py \
        --tenant <uuid> --days 21 [--seed 7] [--enable] [--contest "Осень 2026"]

`--link-stores` заводит СИНТЕТИЧЕСКИЕ объекты реестра для точек без `site_id`
(на staging зеркала реестра нет — бэкфилл связей делался только на проде);
`--enable` включает тенантный тумблер, `--contest` заводит и планирует конкурс
со стартом сегодня (4 недели по 7 дней, лиги — все группы точек), если
активного/запланированного ещё нет. Выгрузка iiko при этом не вызывается.

На проде отказывается работать: `SIGNARIS_HUB_ENVIRONMENT=prod`.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, insert, select

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.org import Store, StoreGroup, StoreGroupMember
from app.models.race import RaceDailyStat
from app.models.shadow import ShadowSite
from app.services.race import engine, gate, iiko_pull, read

_DEMO_STORES = [
    ("Невский", "Н1"),
    ("Арсенальная", "А2"),
    ("Ветеранов д.185", "В3"),
    ("Парнас", "П4"),
    ("Приморская 14", "П5"),
    ("Галерея", "Г6"),
    ("Ладожская", "Л7"),
    ("Купчино", "К8"),
    ("Озерки", "О9"),
    ("Пионерская", "П10"),
    ("Московская", "М11"),
    ("Лиговский", "Л12"),
    ("Чернышевская", "Ч13"),
    ("Василеостровская", "В14"),
    ("Петроградская", "П15"),
    ("Автово", "А16"),
]


async def _create_stores(session, tenant_id: UUID, count: int) -> int:
    """Синтетические точки + две группы («Центр», «Область») — только если точек нет."""
    existing = (
        (await session.execute(select(Store).where(Store.archived_at.is_(None)))).scalars().all()
    )
    if existing:
        return 0
    g1 = StoreGroup(tenant_id=tenant_id, name="Центр")
    g2 = StoreGroup(tenant_id=tenant_id, name="Область")
    session.add_all([g1, g2])
    await session.flush()
    made = 0
    for i, (name, code) in enumerate(_DEMO_STORES[: max(1, min(count, len(_DEMO_STORES)))]):
        store = Store(tenant_id=tenant_id, name=name, code=code)
        session.add(store)
        await session.flush()
        if i % 5 != 4:  # каждая пятая — вне лиг
            session.add(
                StoreGroupMember(
                    tenant_id=tenant_id,
                    group_id=(g1.id if i % 2 == 0 else g2.id),
                    store_id=store.id,
                )
            )
        made += 1
    await session.flush()
    return made


async def _link_stores(session, tenant_id: UUID) -> int:
    """Точкам без реестра — синтетический объект с iiko-ссылкой (staging)."""
    from uuid import uuid4

    stores = list(
        (
            await session.execute(
                select(Store).where(Store.archived_at.is_(None), Store.site_id.is_(None))
            )
        ).scalars()
    )
    for store in stores:
        site_id = uuid4()
        session.add(
            ShadowSite(
                site_id=site_id,
                tenant_id=tenant_id,
                code=store.code,
                name=store.name,
                refs=[
                    {"system": "iiko", "external_id": f"demo-{store.id}"},
                    {"system": "hub", "external_id": str(store.id)},
                ],
                synced_at=datetime.now(UTC),
            )
        )
        store.site_id = site_id
    await session.flush()
    return len(stores)


async def _ensure_contest(session, tenant_id: UUID, title: str) -> None:
    current = await read.current_contest(session, tenant_id)
    if current is not None and current.status in ("scheduled", "active"):
        return
    groups = [g.id for g in (await session.execute(select(StoreGroup))).scalars()]
    today = engine.today_local()
    contest = await engine.create_contest(
        session,
        tenant_id=tenant_id,
        actor_id=None,  # type: ignore[arg-type]
        title=title,
        starts_on=today,
        league_group_ids=groups,
    )
    await engine.schedule(session, contest, today=today, actor_id=None, compute_baselines=None)  # type: ignore[arg-type]


async def main(
    tenant_id: UUID,
    days: int,
    seed: int,
    enable: bool,
    contest_title: str | None,
    link_stores: bool,
    create_stores: int,
) -> int:
    if get_settings().environment == "prod":
        print("Отказ: на проде синтетику не сеем", file=sys.stderr)
        return 2
    rnd = random.Random(seed)  # noqa: S311 — синтетика, не криптография
    today = engine.today_local()
    async with tenant_scoped_session(tenant_id) as session:
        if create_stores:
            print(f"created {await _create_stores(session, tenant_id, create_stores)} demo stores")
        if link_stores:
            print(f"linked {await _link_stores(session, tenant_id)} stores to synthetic sites")
        if enable:
            await gate.set_tenant_enabled(session, tenant_id, True)
        if contest_title:
            await _ensure_contest(session, tenant_id, contest_title)
        contest = await read.current_contest(session, tenant_id)
        if contest is not None:
            depts = [p.department_id for p in await read.load_participants(session, contest)]
        else:
            stores = list(
                (await session.execute(select(Store).where(Store.archived_at.is_(None)))).scalars()
            )
            depts = sorted(
                set(
                    (
                        await engine.department_ids_by_store(
                            session, tenant_id, [s.id for s in stores]
                        )
                    ).values()
                )
            )
        if not depts:
            print("Нет подразделений iiko — привяжите точки к реестру", file=sys.stderr)
            return 1
        day_from = today - timedelta(days=days)
        await session.execute(
            delete(RaceDailyStat).where(
                RaceDailyStat.tenant_id == tenant_id, RaceDailyStat.day >= day_from
            )
        )
        rows = []
        for dept in depts:
            base_avg = rnd.uniform(1.6, 2.6)
            trend = rnd.uniform(-0.004, 0.012)  # дневной дрейф средней
            for i in range(days + 1):
                day = day_from + timedelta(days=i)
                receipts = max(20, int(rnd.gauss(280, 60)))
                avg = max(1.0, base_avg * (1 + trend * i) + rnd.gauss(0, 0.08))
                rows.append(
                    {
                        "tenant_id": tenant_id,
                        "department_id": dept,
                        "day": day,
                        "receipts": receipts,
                        "items": round(receipts * avg, 3),
                        "pulled_at": datetime.now(UTC),
                    }
                )
        await session.execute(insert(RaceDailyStat), rows)
        await iiko_pull.touch_sync_state(session, tenant_id, success=True)
        computed = None
        if contest is not None and contest.status in ("scheduled", "active"):
            races = await read.load_races(session, contest)
            target = None
            if contest.baseline_mode == "race":
                target = next((r for r in races if r.status in ("active", "scheduled")), None)
            rep = await iiko_pull.compute_baselines(
                session, contest=contest, race=target, force=False, pull=False
            )
            computed = rep.computed
        await session.commit()
    print(f"seeded {len(rows)} rows for {len(depts)} departments, baselines: {computed}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, type=UUID)
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--enable", action="store_true")
    ap.add_argument("--contest", default=None)
    ap.add_argument("--link-stores", action="store_true")
    ap.add_argument("--create-stores", type=int, default=0)
    ns = ap.parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                ns.tenant, ns.days, ns.seed, ns.enable, ns.contest, ns.link_stores, ns.create_stores
            )
        )
    )
