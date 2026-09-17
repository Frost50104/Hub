"""Сборка ответов экранов гонки — только чтение.

`build_track` — единственный сборщик трека: им отвечают и `GET /learn/race`,
и публичная ТВ-ручка (`my_store_id=None`). Позиция «сейчас» считается из
`race_daily_stats` за [старт заезда, min(сегодня, конец)], итоги завершённых
заездов берутся замороженными из `race_results`, динамика — против последнего
суточного снимка.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Store
from app.models.race import (
    Race,
    RaceContest,
    RaceContestLeague,
    RaceDailyStat,
    RaceParticipant,
    RaceResult,
    RaceSnapshot,
    RaceSyncState,
)
from app.services.iiko import service as iiko_service
from app.services.race import math as m
from app.services.timefmt import display_tz

# Часовой тик выгрузки (ops/systemd/signaris-hub-race-sync.timer).
SYNC_MINUTE = 40


def local_instant(d: date, *, next_day: bool = False) -> datetime:
    """Полночь календарного дня в display tz — граница заезда для отсчёта."""
    dd = d + timedelta(days=1) if next_day else d
    return datetime.combine(dd, time.min, tzinfo=display_tz())


def next_refresh_after(now: datetime) -> datetime:
    """Ближайший часовой тик выгрузки после `now` (UTC)."""
    base = now.astimezone(UTC).replace(second=0, microsecond=0)
    candidate = base.replace(minute=SYNC_MINUTE)
    if candidate <= base:
        candidate += timedelta(hours=1)
    return candidate


def live_positions_stmt(
    tenant_id: UUID, department_ids: list[str], day_from: date, day_to: date
) -> Select:
    """Накопленные чеки/позиции по подразделениям за окно (compile-тест)."""
    return (
        select(
            RaceDailyStat.department_id,
            func.coalesce(func.sum(RaceDailyStat.receipts), 0),
            func.coalesce(func.sum(RaceDailyStat.items), 0),
        )
        .where(
            RaceDailyStat.tenant_id == tenant_id,
            RaceDailyStat.department_id.in_(department_ids),
            RaceDailyStat.day >= day_from,
            RaceDailyStat.day <= day_to,
        )
        .group_by(RaceDailyStat.department_id)
    )


async def cumulative_by_department(
    session: AsyncSession,
    tenant_id: UUID,
    department_ids: list[str],
    day_from: date,
    day_to: date,
) -> dict[str, tuple[int, float]]:
    if not department_ids or day_to < day_from:
        return {}
    rows = await session.execute(live_positions_stmt(tenant_id, department_ids, day_from, day_to))
    return {dept: (int(r), float(i)) for dept, r, i in rows}


@dataclass(frozen=True)
class ParticipantInfo:
    store_id: UUID
    name: str
    code: str | None
    department_id: str
    league_id: UUID | None
    excluded_at: datetime | None
    exclude_reason: str | None


async def load_participants(
    session: AsyncSession, contest: RaceContest, *, include_excluded: bool = False
) -> list[ParticipantInfo]:
    stmt = (
        select(RaceParticipant, Store.name, Store.code)
        .join(Store, Store.id == RaceParticipant.store_id)
        .where(RaceParticipant.contest_id == contest.id)
        .order_by(Store.name)
    )
    if not include_excluded:
        stmt = stmt.where(RaceParticipant.excluded_at.is_(None))
    return [
        ParticipantInfo(
            store_id=p.store_id,
            name=name,
            code=code,
            department_id=p.department_id,
            league_id=p.league_id,
            excluded_at=p.excluded_at,
            exclude_reason=p.exclude_reason,
        )
        for p, name, code in (await session.execute(stmt)).all()
    ]


async def load_leagues(session: AsyncSession, contest: RaceContest) -> list[RaceContestLeague]:
    return list(
        (
            await session.execute(
                select(RaceContestLeague)
                .where(RaceContestLeague.contest_id == contest.id)
                .order_by(RaceContestLeague.position, RaceContestLeague.name)
            )
        ).scalars()
    )


async def load_races(session: AsyncSession, contest: RaceContest) -> list[Race]:
    return list(
        (
            await session.execute(
                select(Race).where(Race.contest_id == contest.id).order_by(Race.seq)
            )
        ).scalars()
    )


def race_dict(race: Race) -> dict[str, Any]:
    return {
        "id": race.id,
        "seq": race.seq,
        "starts_on": race.starts_on,
        "ends_on": race.ends_on,
        "status": race.status,
        "starts_at": local_instant(race.starts_on),
        "ends_at": local_instant(race.ends_on, next_day=True),
        "finish_reason": race.finish_reason,
    }


_CONTEST_PRIORITY = {"active": 0, "scheduled": 1, "finished": 2, "cancelled": 3}


async def current_contest(session: AsyncSession, tenant_id: UUID) -> RaceContest | None:
    """Конкурс для показа: активный → ближайший запланированный → последний
    завершённый. Черновики людям не показываются."""
    rows = list(
        (
            await session.execute(
                select(RaceContest).where(
                    RaceContest.tenant_id == tenant_id,
                    RaceContest.status.in_(tuple(_CONTEST_PRIORITY)),
                )
            )
        ).scalars()
    )
    if not rows:
        return None

    def key(c: RaceContest) -> tuple[int, float]:
        prio = _CONTEST_PRIORITY[c.status]
        # запланированный — ближайший (раньше лучше), завершённый — свежий
        return (prio, c.starts_on.toordinal() if prio == 1 else -c.starts_on.toordinal())

    return min(rows, key=key)


def pick_display_race(races: list[Race]) -> Race | None:
    """Активный → ближайший запланированный → последний завершённый."""
    active = [r for r in races if r.status == "active"]
    if active:
        return active[0]
    scheduled = [r for r in races if r.status == "scheduled"]
    if scheduled:
        return min(scheduled, key=lambda r: r.seq)
    finished = [r for r in races if r.status == "finished"]
    if finished:
        return max(finished, key=lambda r: r.seq)
    return None


@dataclass(frozen=True)
class LiveRow:
    rank: m.RankRow
    base: float | None
    receipts: int
    items: float


async def live_rows(
    session: AsyncSession,
    contest: RaceContest,
    race: Race,
    *,
    through_day: date,
    participants: list[ParticipantInfo],
    baselines: dict[UUID, Any],
) -> list[LiveRow]:
    """Позиции «сейчас»: накопленное с начала заезда против эффективной базы."""
    sums = await cumulative_by_department(
        session,
        contest.tenant_id,
        [p.department_id for p in participants],
        race.starts_on,
        through_day,
    )
    out: list[LiveRow] = []
    for p in participants:
        receipts, items = sums.get(p.department_id, (0, 0.0))
        avg = m.compute_avg(items, receipts)
        b = baselines.get(p.store_id)
        base = b.value if b is not None else None
        cells, needs_baseline = m.compute_cells(avg, base)
        out.append(
            LiveRow(
                rank=m.RankRow(
                    store_id=p.store_id,
                    name=p.name,
                    cells=cells,
                    pct=m.compute_pct(avg, base),
                    avg=avg,
                    needs_baseline=needs_baseline,
                    league_id=p.league_id,
                ),
                base=base,
                receipts=receipts,
                items=items,
            )
        )
    return out


async def previous_close_cells(
    session: AsyncSession, race: Race, before_day: date
) -> dict[UUID, int]:
    """Клетки последнего снимка до `before_day` по каждой точке (DISTINCT ON)."""
    rows = await session.execute(
        select(RaceSnapshot.store_id, RaceSnapshot.cells)
        .where(RaceSnapshot.race_id == race.id, RaceSnapshot.day < before_day)
        .distinct(RaceSnapshot.store_id)
        .order_by(RaceSnapshot.store_id, RaceSnapshot.day.desc())
    )
    return {store_id: int(cells) for store_id, cells in rows}


async def frozen_results(session: AsyncSession, race: Race) -> list[RaceResult]:
    return list(
        (await session.execute(select(RaceResult).where(RaceResult.race_id == race.id))).scalars()
    )


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _participant_payload(
    p: ParticipantInfo,
    *,
    cells: int,
    pct: float | None,
    avg: float | None,
    base: float | None,
    receipts: int,
    items: float,
    needs_baseline: bool,
    place: int | None,
    place_in_league: int | None,
    dynamics: str | None,
    prev_close_cells: int | None,
) -> dict[str, Any]:
    return {
        "store_id": p.store_id,
        "name": p.name,
        "code": p.code,
        "league_id": p.league_id,
        "cells": cells,
        "pct": pct,
        "avg": None if avg is None else round(avg, 2),
        "base": None if base is None else round(base, 2),
        "receipts": receipts,
        "items": round(items, 1),
        "needs_baseline": needs_baseline,
        "place": place,
        "place_in_league": place_in_league,
        "dynamics": dynamics,
        "prev_close_cells": prev_close_cells,
    }


async def participants_for_race(
    session: AsyncSession,
    contest: RaceContest,
    race: Race | None,
    *,
    today: date,
    participants: list[ParticipantInfo],
) -> list[dict[str, Any]]:
    """Строки трека для заезда: живые (active), замороженные (finished) или стартовые."""
    from app.services.race.baselines import load_baselines

    by_store = {p.store_id: p for p in participants}
    if race is None:
        return [
            _participant_payload(
                p,
                cells=m.START_CELLS,
                pct=None,
                avg=None,
                base=None,
                receipts=0,
                items=0.0,
                needs_baseline=True,
                place=None,
                place_in_league=None,
                dynamics=None,
                prev_close_cells=None,
            )
            for p in participants
        ]
    if race.status == "finished":
        out: list[dict[str, Any]] = []
        for r in await frozen_results(session, race):
            p = by_store.get(r.store_id)
            if p is None:
                continue
            out.append(
                _participant_payload(
                    p,
                    cells=int(r.cells),
                    pct=_f(r.pct),
                    avg=_f(r.avg),
                    base=_f(r.base),
                    receipts=int(r.receipts),
                    items=float(r.items),
                    needs_baseline=bool(r.needs_baseline),
                    place=r.place,
                    place_in_league=r.place_in_league,
                    dynamics=None,
                    prev_close_cells=None,
                )
            )
        out.sort(key=lambda d: (d["place"] is None, d["place"] or 0, d["name"].casefold()))
        return out

    baselines = await load_baselines(session, contest, race.id)
    if race.status == "scheduled":
        return [
            _participant_payload(
                p,
                cells=m.START_CELLS,
                pct=None,
                avg=None,
                base=(baselines[p.store_id].value if p.store_id in baselines else None),
                receipts=0,
                items=0.0,
                needs_baseline=(p.store_id not in baselines or baselines[p.store_id].value is None),
                place=None,
                place_in_league=None,
                dynamics=None,
                prev_close_cells=None,
            )
            for p in participants
        ]

    through = min(today, race.ends_on)
    rows = await live_rows(
        session, contest, race, through_day=through, participants=participants, baselines=baselines
    )
    ranked = {r.store_id: r for r in m.rank([lr.rank for lr in rows])}
    prev = await previous_close_cells(session, race, through)
    out = []
    for lr in rows:
        rr = ranked[lr.rank.store_id]
        p = by_store[lr.rank.store_id]
        prev_cells = prev.get(p.store_id)
        out.append(
            _participant_payload(
                p,
                cells=rr.cells,
                pct=rr.pct,
                avg=rr.avg,
                base=lr.base,
                receipts=lr.receipts,
                items=lr.items,
                needs_baseline=rr.needs_baseline,
                place=rr.place,
                place_in_league=rr.place_in_league,
                dynamics=m.dynamics(rr.cells, prev_cells),
                prev_close_cells=prev_cells,
            )
        )
    out.sort(key=lambda d: (d["place"] is None, d["place"] or 0, d["name"].casefold()))
    return out


async def standings_payload(
    session: AsyncSession,
    contest: RaceContest,
    races: list[Race],
    participants: list[ParticipantInfo],
) -> list[dict[str, Any]]:
    finished = [r for r in races if r.status == "finished"]
    if not finished:
        return []
    per_race: list[list[m.ResultRow]] = []
    for race in finished:
        per_race.append(
            [
                m.ResultRow(
                    store_id=r.store_id,
                    place=r.place,
                    place_in_league=r.place_in_league,
                    pct=_f(r.pct),
                    league_id=r.league_id,
                )
                for r in await frozen_results(session, race)
            ]
        )
    rows = m.standings(
        per_race,
        [m.ParticipantRow(p.store_id, p.name, p.league_id) for p in participants],
    )
    return [
        {
            "store_id": s.store_id,
            "name": s.name,
            "league_id": s.league_id,
            "place": s.place,
            "points": s.points,
            "pct_sum": s.pct_sum,
            "races_counted": s.races_counted,
            "missed_races": s.missed_races,
            "place_in_league": s.place_in_league,
            "points_in_league": s.points_in_league,
        }
        for s in rows
    ]


def contest_dict(
    contest: RaceContest, leagues: list[RaceContestLeague], races: list[Race]
) -> dict[str, Any]:
    return {
        "id": contest.id,
        "title": contest.title,
        "status": contest.status,
        "starts_on": contest.starts_on,
        "ends_on": contest.ends_on,
        "race_length_days": contest.race_length_days,
        "weeks_total": contest.weeks_total,
        "baseline_mode": contest.baseline_mode,
        "baseline_days": contest.baseline_days,
        "leagues": [{"id": lg.id, "name": lg.name} for lg in leagues],
        "races": [race_dict(r) for r in races],
    }


async def build_track(
    session: AsyncSession,
    contest: RaceContest | None,
    *,
    today: date,
    my_store_id: UUID | None,
    tenant_id: UUID,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "configured": iiko_service.is_configured(),
        "server_now": now,
        "contest": None,
        "race": None,
        "my_store_id": my_store_id,
        "participants": [],
        "standings": [],
        "finished_races": [],
        "as_of": None,
        "next_refresh_at": next_refresh_after(now),
    }
    state = await session.get(RaceSyncState, tenant_id)
    if state is not None:
        payload["as_of"] = state.last_success_at
    if contest is None:
        return payload

    races = await load_races(session, contest)
    leagues = await load_leagues(session, contest)
    participants = await load_participants(session, contest)
    race = pick_display_race(races)
    payload["contest"] = contest_dict(contest, leagues, races)
    if race is not None:
        through = min(today, race.ends_on) if race.status != "scheduled" else None
        payload["race"] = {
            **race_dict(race),
            "days_total": (race.ends_on - race.starts_on).days + 1,
            "day_index": (None if through is None else max(0, (through - race.starts_on).days + 1)),
            "data_through": through,
        }
    payload["participants"] = await participants_for_race(
        session, contest, race, today=today, participants=participants
    )
    payload["standings"] = await standings_payload(session, contest, races, participants)
    finished_payload = []
    for r in races:
        if r.status != "finished":
            continue
        winner = next((x.store_id for x in await frozen_results(session, r) if x.place == 1), None)
        finished_payload.append({**race_dict(r), "winner_store_id": winner})
    payload["finished_races"] = finished_payload
    return payload


async def race_results_view(
    session: AsyncSession, contest: RaceContest, race: Race, *, today: date
) -> dict[str, Any]:
    participants = await load_participants(session, contest)
    rows = await participants_for_race(
        session, contest, race, today=today, participants=participants
    )
    return {"race": race_dict(race), "results": rows}


async def store_history(
    session: AsyncSession, contest: RaceContest, store_id: UUID
) -> list[dict[str, Any]]:
    races = await load_races(session, contest)
    results = {
        r.race_id: r
        for r in (
            await session.execute(select(RaceResult).where(RaceResult.store_id == store_id))
        ).scalars()
    }
    out: list[dict[str, Any]] = []
    for race in races:
        r = results.get(race.id)
        out.append(
            {
                **race_dict(race),
                "race_id": race.id,
                "cells": None if r is None else int(r.cells),
                "pct": None if r is None else _f(r.pct),
                "place": None if r is None else r.place,
                "place_in_league": None if r is None else r.place_in_league,
            }
        )
    return out


async def race_chart(
    session: AsyncSession, contest: RaceContest, race: Race, store_id: UUID, *, today: date
) -> dict[str, Any]:
    from app.services.race.baselines import load_baselines

    snaps = list(
        (
            await session.execute(
                select(RaceSnapshot)
                .where(RaceSnapshot.race_id == race.id, RaceSnapshot.store_id == store_id)
                .order_by(RaceSnapshot.day)
            )
        ).scalars()
    )
    points = [
        {
            "day": s.day,
            "cells": int(s.cells),
            "pct": _f(s.pct),
            "avg": _f(s.avg),
            "is_record": bool(s.is_record),
            "live": False,
        }
        for s in snaps
    ]
    base: float | None = _f(snaps[-1].base) if snaps else None
    if (
        race.status == "active"
        and today <= race.ends_on
        and not any(p["day"] == today for p in points)
    ):
        participants = [
            p for p in await load_participants(session, contest) if p.store_id == store_id
        ]
        if participants:
            baselines = await load_baselines(session, contest, race.id)
            rows = await live_rows(
                session,
                contest,
                race,
                through_day=today,
                participants=participants,
                baselines=baselines,
            )
            if rows:
                lr = rows[0]
                base = lr.base if base is None else base
                points.append(
                    {
                        "day": today,
                        "cells": lr.rank.cells,
                        "pct": lr.rank.pct,
                        "avg": None if lr.rank.avg is None else round(lr.rank.avg, 2),
                        "is_record": False,
                        "live": True,
                    }
                )
    return {
        "race_id": race.id,
        "store_id": store_id,
        "starts_on": race.starts_on,
        "ends_on": race.ends_on,
        "base": None if base is None else round(base, 2),
        "points": points,
    }
