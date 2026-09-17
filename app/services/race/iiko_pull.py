"""Выгрузка чеков iiko в `race_daily_stats` и расчёт базы.

- один OLAP-вызов на всю сеть за окно ≤ 14 дней, под fenced-локом слота
  лицензии на время ОДНОЙ сессии (не поверх записи в БД);
- replace-window: окно стирается и пишется заново одной транзакцией, чтобы
  подразделение, чей день в iiko исправили в ноль, исчезло;
- защита от пустого ответа: пусто при ненулевом окне = сбой iiko, окно не
  трогаем;
- КАЖДЫЙ вызов гейтится `race_sync_enabled`: staging делит с продом креды
  iiko, но не Redis-DB, и его лок проду не виден.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import structlog
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.race import Race, RaceContest, RaceDailyStat, RaceParticipant, RaceSyncState
from app.services.iiko import service as iiko_service
from app.services.iiko.reports import DailyRow, fetch_race_daily
from app.services.race import gate
from app.services.race.baselines import get_baseline_row, upsert_baseline
from app.services.race.math import chunk_period, compute_avg, retro_period

log = structlog.get_logger("race.iiko_pull")

JOB_LOCK_WAIT_SEC = 45.0
BASELINE_WINDOW_DAYS = 14
MAX_MANUAL_PULL_DAYS = 31


class RaceSyncDisabled(RuntimeError):
    """Обращения к iiko из модуля выключены (`SIGNARIS_HUB_RACE_SYNC_ENABLED=false`)."""


@dataclass(frozen=True)
class PullReport:
    day_from: date
    day_to: date
    rows: int
    departments: int
    days: int
    written: bool
    skipped_empty: bool
    dry_run: bool


async def _fetch(
    tenant_id: UUID, day_from: date, day_to: date, *, wait_sec: float
) -> list[DailyRow]:
    if not gate.sync_enabled():
        raise RaceSyncDisabled("Выгрузка iiko для гонки на этом окружении выключена")
    client = iiko_service.race_client()  # IikoNotConfigured — наружу
    async with iiko_service.iiko_session_lock(tenant_id, wait_sec=wait_sec), client as c:
        return await fetch_race_daily(c, date_from=day_from, date_to=day_to)


async def touch_sync_state(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    error: str | None = None,
    success: bool = False,
    close_day: date | None = None,
) -> None:
    row = await session.get(RaceSyncState, tenant_id)
    if row is None:
        row = RaceSyncState(tenant_id=tenant_id)
        session.add(row)
    now = datetime.now(UTC)
    if error is not None or success:
        row.last_pull_at = now
    if success:
        row.last_success_at = now
        row.last_error = None
    if error is not None:
        row.last_error = error[:1000]
    if close_day is not None:
        row.last_close_day = close_day
    await session.flush()


async def pull_days(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    day_from: date,
    day_to: date,
    dry_run: bool = False,
    wait_sec: float = JOB_LOCK_WAIT_SEC,
) -> PullReport:
    """Выгрузить окно дней и заменить его в `race_daily_stats`.

    Ошибки iiko (`IikoBusy`, `IikoError`, `IikoNotConfigured`) уходят наружу —
    вызывающий решает, пропустить тик или ответить 409/502; в `race_sync_state`
    они попадают через `touch_sync_state(error=…)` там же.
    """
    if day_to < day_from:
        raise ValueError("day_to раньше day_from")
    try:
        rows = await _fetch(tenant_id, day_from, day_to, wait_sec=wait_sec)
    except Exception as e:
        if not dry_run:
            await touch_sync_state(session, tenant_id, error=f"{type(e).__name__}: {e}")
        raise
    departments = {r.department_id for r in rows}
    days = {r.day for r in rows}
    report = PullReport(
        day_from=day_from,
        day_to=day_to,
        rows=len(rows),
        departments=len(departments),
        days=len(days),
        written=False,
        skipped_empty=False,
        dry_run=dry_run,
    )
    if dry_run:
        return report

    existing = (
        await session.execute(
            select(func.coalesce(func.sum(RaceDailyStat.receipts), 0)).where(
                RaceDailyStat.tenant_id == tenant_id,
                RaceDailyStat.day >= day_from,
                RaceDailyStat.day <= day_to,
            )
        )
    ).scalar_one()
    if not rows and existing > 0:
        log.warning(
            "race_sync.empty_window_skipped",
            tenant_id=str(tenant_id),
            day_from=str(day_from),
            day_to=str(day_to),
            existing_receipts=int(existing),
        )
        await touch_sync_state(
            session, tenant_id, error="iiko вернул пустое окно при ненулевых данных"
        )
        return PullReport(**{**report.__dict__, "skipped_empty": True})

    await session.execute(
        delete(RaceDailyStat).where(
            RaceDailyStat.tenant_id == tenant_id,
            RaceDailyStat.day >= day_from,
            RaceDailyStat.day <= day_to,
        )
    )
    if rows:
        now = datetime.now(UTC)
        await session.execute(
            insert(RaceDailyStat),
            [
                {
                    "tenant_id": tenant_id,
                    "department_id": r.department_id,
                    "day": r.day,
                    "receipts": r.receipts,
                    "items": r.items,
                    "pulled_at": now,
                }
                for r in rows
            ],
        )
    await touch_sync_state(session, tenant_id, success=True)
    log.info(
        "race_sync.window_written",
        tenant_id=str(tenant_id),
        day_from=str(day_from),
        day_to=str(day_to),
        rows=len(rows),
        departments=len(departments),
    )
    return PullReport(**{**report.__dict__, "written": True})


@dataclass(frozen=True)
class BaselineReport:
    period_from: date
    period_to: date
    computed: int
    skipped_manual: int
    empty: int
    pulled: bool


async def aggregate_by_department(
    session: AsyncSession, tenant_id: UUID, day_from: date, day_to: date
) -> dict[str, tuple[int, float]]:
    rows = await session.execute(
        select(
            RaceDailyStat.department_id,
            func.coalesce(func.sum(RaceDailyStat.receipts), 0),
            func.coalesce(func.sum(RaceDailyStat.items), 0),
        )
        .where(
            RaceDailyStat.tenant_id == tenant_id,
            RaceDailyStat.day >= day_from,
            RaceDailyStat.day <= day_to,
        )
        .group_by(RaceDailyStat.department_id)
    )
    return {dept: (int(r), float(i)) for dept, r, i in rows}


async def compute_baselines(
    session: AsyncSession,
    *,
    contest: RaceContest,
    race: Race | None,
    force: bool = False,
    pull: bool = True,
    set_by: UUID | None = None,
) -> BaselineReport:
    """База = средняя наполняемость за ретро-окно до старта (конкурса или заезда).

    `pull=False` — только пересчитать из уже выгруженных дней (staging,
    где iiko недоступен, или повторный расчёт без похода в iiko).
    """
    anchor = race.starts_on if race is not None else contest.starts_on
    period_from, period_to = retro_period(anchor, int(contest.baseline_days))
    pulled = False
    if pull:
        for a, b in chunk_period(period_from, period_to, BASELINE_WINDOW_DAYS):
            await pull_days(session, tenant_id=contest.tenant_id, day_from=a, day_to=b)
        pulled = True
    sums = await aggregate_by_department(session, contest.tenant_id, period_from, period_to)
    participants = (
        (
            await session.execute(
                select(RaceParticipant).where(
                    RaceParticipant.contest_id == contest.id,
                    RaceParticipant.excluded_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    race_id = race.id if race is not None else None
    computed = skipped = empty = 0
    for p in participants:
        current = await get_baseline_row(session, contest.id, p.store_id, race_id)
        if current is not None and current.source == "manual" and not force:
            skipped += 1
            continue
        receipts, items = sums.get(p.department_id, (0, 0.0))
        value = compute_avg(items, receipts)
        if value is None:
            empty += 1
        await upsert_baseline(
            session,
            contest=contest,
            store_id=p.store_id,
            race_id=race_id,
            value=value,
            source="iiko",
            receipts=receipts,
            items=items,
            period_from=period_from,
            period_to=period_to,
            set_by=set_by,
        )
        computed += 1
    return BaselineReport(
        period_from=period_from,
        period_to=period_to,
        computed=computed,
        skipped_manual=skipped,
        empty=empty,
        pulled=pulled,
    )


def lock_tenant_sql() -> str:
    """Advisory xact-lock гонки на тенант — только вокруг ЗАПИСИ, не поверх OLAP."""
    return "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"


async def lock_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(text(lock_tenant_sql()), {"key": f"hub_race:{tenant_id}"})
