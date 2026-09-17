#!/usr/bin/env python3
"""Создать и запланировать конкурс «Гусиной гонки» из консоли сервера.

Тот же путь, что у кнопки «Запланировать» в админке: участники из реестра
объектов, лиги из групп точек (`--leagues auto`), база из живого iiko за
ретро-период. После планирования — сверка с iiko: сумма позиций за ретро-окно
против отчёта «Позиции меню» (тот же фильтр, обязана сойтись), число чеков
против «Выручки» (может быть чуть меньше — чеки из одних немениюшных строк).

    cd /opt/signaris-hub && ./.venv/bin/python scripts/race_create_contest.py \\
        --tenant-slug uppetit --title "Гусиная гонка — осень 2026" \\
        --start 2026-09-18 [--weeks 4] [--length 7] [--baseline-days 28] \\
        [--leagues auto|none] [--no-check]

Актор в аудите — None («создано скриптом»).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import func, select

from app.db import tenant_scoped_session
from app.models.org import Store, StoreGroup
from app.models.race import RaceDailyStat, RaceSyncState
from app.models.shadow import ShadowTenant
from app.services.iiko import service as iiko_service
from app.services.iiko.reports import (
    F_DEPARTMENT,
    F_DISH,
    F_DISH_TYPE,
    F_ORDERS,
    F_QTY,
    MENU_DISH_TYPES,
    _num,
)
from app.services.race import engine, gate, iiko_pull, read
from app.services.race.baselines import load_baselines
from app.services.race.math import retro_period


async def _cross_check(session, tenant_id, period_from: date, period_to: date) -> None:
    receipts, items = (
        await session.execute(
            select(
                func.coalesce(func.sum(RaceDailyStat.receipts), 0),
                func.coalesce(func.sum(RaceDailyStat.items), 0),
            ).where(
                RaceDailyStat.tenant_id == tenant_id,
                RaceDailyStat.day >= period_from,
                RaceDailyStat.day <= period_to,
            )
        )
    ).one()
    print(
        f"race_daily_stats за {period_from}–{period_to}: "
        f"чеков {receipts}, позиций {float(items):.1f}"
    )
    async with (
        iiko_service.iiko_session_lock(tenant_id, wait_sec=45),
        iiko_service.race_client() as c,
    ):
        menu = await c.olap(
            report_type="SALES",
            date_from=period_from,
            date_to=period_to,
            group_by=[F_DISH],
            aggregate=[F_QTY],
            extra_filters={F_DISH_TYPE: {"filterType": "IncludeValues", "values": MENU_DISH_TYPES}},
        )
        revenue = await c.olap(
            report_type="SALES",
            date_from=period_from,
            date_to=period_to,
            group_by=[F_DEPARTMENT],
            aggregate=[F_ORDERS],
        )
    menu_qty = sum(_num(r, F_QTY) for r in menu)
    all_receipts = sum(_num(r, F_ORDERS) for r in revenue)
    print(
        f"«Позиции меню» (тот же фильтр): {menu_qty:.1f} → "
        f"расхождение {float(items) - menu_qty:+.1f}"
    )
    print(
        f"«Выручка», чеков всего: {all_receipts:.0f} → "
        f"гонка видит {int(receipts)} ({int(receipts) - all_receipts:+.0f})"
    )


async def main(ns: argparse.Namespace) -> int:
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        tenant_id = (
            await scan.execute(select(ShadowTenant.id).where(ShadowTenant.slug == ns.tenant_slug))
        ).scalar_one_or_none()
    if tenant_id is None:
        print(f"Тенант «{ns.tenant_slug}» не найден", file=sys.stderr)
        return 1
    today = engine.today_local()
    start = date.fromisoformat(ns.start) if ns.start else today
    async with tenant_scoped_session(tenant_id) as session:
        if not await gate.race_enabled_for(session, tenant_id):
            print("Гонка выключена (env или тумблер тенанта) — сначала включите", file=sys.stderr)
            return 2
        current = await read.current_contest(session, tenant_id)
        if current is not None and current.status in ("scheduled", "active"):
            print(
                f"Уже есть конкурс «{current.title}» ({current.status}) — второй не заводим",
                file=sys.stderr,
            )
            return 3
        league_ids = []
        if ns.leagues == "auto":
            groups = list((await session.execute(select(StoreGroup))).scalars())
            league_ids = [g.id for g in groups]
        contest = await engine.create_contest(
            session,
            tenant_id=tenant_id,
            actor_id=None,  # type: ignore[arg-type]
            title=ns.title,
            starts_on=start,
            race_length_days=ns.length,
            weeks_total=ns.weeks,
            baseline_mode="contest",
            baseline_days=ns.baseline_days,
            league_group_ids=[],
        )
        if league_ids:
            try:
                await engine.apply_leagues(session, contest, league_ids)
            except engine.RaceValidationError as e:
                print(f"Лиги не назначены: {e}")
        parts = await read.load_participants(session, contest, include_excluded=True)
        included = [p for p in parts if p.excluded_at is None]
        dupes = [p for p in parts if p.exclude_reason == "duplicate"]
        stores = dict(
            (
                await session.execute(
                    select(Store.id, Store.name).where(Store.archived_at.is_(None))
                )
            ).all()
        )
        unlinked = [n for sid, n in stores.items() if sid not in {p.store_id for p in parts}]
        print(
            f"Конкурс «{contest.title}» {contest.starts_on}–{contest.ends_on}, "
            f"заезд {ns.length} дн., недель {ns.weeks}"
        )
        print(
            f"Участники: {len(included)} включены, {len(dupes)} исключены как дубли "
            f"подразделения, {len(unlinked)} без реестра"
        )
        for d in dupes:
            twin = next((p for p in included if p.department_id == d.department_id), None)
            print(f"  дубль: «{d.name}» ↔ участвует «{twin.name if twin else '?'}»")
        for n in unlinked:
            print(f"  без реестра: «{n}»")
        if ns.dry_run:
            await session.rollback()
            print("dry-run: откат")
            return 0
        report = await engine.schedule(
            session,
            contest,
            today=today,
            actor_id=None,  # type: ignore[arg-type]
            compute_baselines=iiko_pull.compute_baselines if gate.sync_enabled() else None,
        )
        await session.commit()
        races = await read.load_races(session, contest)
        print(
            f"Статус: {contest.status}; заезды: "
            + ", ".join(f"№{r.seq} {r.starts_on}–{r.ends_on} ({r.status})" for r in races)
        )
        baselines = await load_baselines(session, contest, None)
        values = sorted(b.value for b in baselines.values() if b.value is not None)
        print(
            f"База посчитана у {len(values)} из {len(included)}; "
            f"без базы: {len(report.needs_baseline_store_ids)}"
        )
        if values:
            print(
                f"  диапазон {values[0]:.2f} … {values[-1]:.2f}, "
                f"медиана {values[len(values) // 2]:.2f}"
            )
        for sid in report.needs_baseline_store_ids:
            print(f"  без базы: «{stores.get(sid, sid)}»")
        state = await session.get(RaceSyncState, tenant_id)
        if state is not None:
            print(f"Выгрузка: успех {state.last_success_at}, ошибка {state.last_error!r}")
        if not ns.no_check and report.baselines_computed:
            period_from, period_to = retro_period(contest.starts_on, contest.baseline_days)
            await _cross_check(session, tenant_id, period_from, period_to)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--start", default=None, help="YYYY-MM-DD, по умолчанию сегодня (MSK)")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--length", type=int, default=7, choices=(7, 14))
    ap.add_argument("--baseline-days", type=int, default=28)
    ap.add_argument("--leagues", choices=("auto", "none"), default="auto")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-check", action="store_true")
    raise SystemExit(asyncio.run(main(ap.parse_args())))
