"""Жизненный цикл конкурса: участники, лиги, расписание, закрытие дня, итоги,
уведомления. Запись — под advisory-локом тенанта, взятым ПОСЛЕ любых походов
в iiko (лок только вокруг записи).

Все функции получают `today`/`close_day` явно (московская дата — `today_local()`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile
from app.models.org import Store, StoreGroup, StoreGroupMember
from app.models.race import (
    Race,
    RaceBaseline,
    RaceContest,
    RaceContestLeague,
    RaceParticipant,
    RaceResult,
    RaceSnapshot,
)
from app.models.shadow import ShadowSite
from app.services import audit
from app.services.audience_resolver import learning_population_filter
from app.services.notify_batch import PushBatch, queue_many, schedule_push_batch
from app.services.race import gate, read
from app.services.race import math as m
from app.services.race.baselines import (
    get_baseline_row,
    has_iiko_baseline,
    load_baselines,
    upsert_baseline,
)
from app.services.race.iiko_pull import lock_tenant
from app.services.timefmt import display_tz, fmt_day, fmt_day_range

log = structlog.get_logger("race.engine")

NOTIFY_FROM_HOUR = 9
KIND_STARTED = "race.started"
KIND_RECORD = "race.record"


class RaceValidationError(ValueError):
    """422 — тело запроса противоречит правилам конкурса."""


class RaceConflictError(ValueError):
    """409 — действие невозможно в текущем состоянии."""


def today_local() -> date:
    return datetime.now(display_tz()).date()


def _now() -> datetime:
    return datetime.now(UTC)


# ─── участники ──────────────────────────────────────────────────────────────


async def department_ids_by_store(
    session: AsyncSession, tenant_id: UUID, store_ids: list[UUID]
) -> dict[UUID, str]:
    """store_id → Department.Id через реестр объектов (stores.site_id → refs)."""
    if not store_ids:
        return {}
    site_by_store = dict(
        (
            await session.execute(
                select(Store.id, Store.site_id).where(
                    Store.id.in_(store_ids), Store.site_id.is_not(None)
                )
            )
        ).all()
    )
    if not site_by_store:
        return {}
    dept_by_site: dict[UUID, str] = {}
    for site_id, refs in (
        await session.execute(
            select(ShadowSite.site_id, ShadowSite.refs).where(
                ShadowSite.site_id.in_(set(site_by_store.values()))
            )
        )
    ).all():
        ids = sorted(
            str(ref["external_id"])
            for ref in (refs or [])
            if ref.get("system") == "iiko" and ref.get("external_id")
        )
        if ids:
            dept_by_site[site_id] = ids[0]
    return {sid: dept_by_site[site] for sid, site in site_by_store.items() if site in dept_by_site}


@dataclass
class ParticipantsReport:
    included: list[UUID] = field(default_factory=list)
    duplicates: list[UUID] = field(default_factory=list)
    unlinked_store_ids: list[UUID] = field(default_factory=list)


async def materialize_participants(
    session: AsyncSession, contest: RaceContest, *, actor_id: UUID | None = None
) -> ParticipantsReport:
    """Неархивные точки с подразделением iiko → участники; один живой на
    подразделение (первый по имени), остальные `excluded (duplicate)`.
    Повторный вызов добавляет только новых, существующие строки не трогает."""
    stores = list(
        (
            await session.execute(
                select(Store).where(Store.archived_at.is_(None)).order_by(Store.name, Store.id)
            )
        ).scalars()
    )
    dept_by_store = await department_ids_by_store(
        session, contest.tenant_id, [s.id for s in stores]
    )
    existing = {
        p.store_id: p
        for p in (
            await session.execute(
                select(RaceParticipant).where(RaceParticipant.contest_id == contest.id)
            )
        ).scalars()
    }
    held: set[str] = {p.department_id for p in existing.values() if p.excluded_at is None}
    report = ParticipantsReport()
    for store in sorted(stores, key=lambda s: (s.name.casefold(), str(s.id))):
        dept = dept_by_store.get(store.id)
        if dept is None:
            report.unlinked_store_ids.append(store.id)
            continue
        if store.id in existing:
            continue
        row = RaceParticipant(
            tenant_id=contest.tenant_id,
            contest_id=contest.id,
            store_id=store.id,
            department_id=dept,
        )
        if dept in held:
            row.excluded_at = _now()
            row.excluded_by = actor_id
            row.exclude_reason = "duplicate"
            report.duplicates.append(store.id)
        else:
            held.add(dept)
            report.included.append(store.id)
        session.add(row)
    await session.flush()
    return report


async def apply_leagues(
    session: AsyncSession, contest: RaceContest, store_group_ids: list[UUID]
) -> None:
    """Снимок лиг из «групп точек»; точка в ≥2 выбранных группах — 422.

    Членства читаются ТОЛЬКО по неархивным точкам: `org_snapshot` отдаёт и
    архивные, и 422 «в двух лигах» называл бы закрытую точку.
    """
    ids = list(dict.fromkeys(store_group_ids))
    groups = (
        {
            g.id: g
            for g in (
                await session.execute(select(StoreGroup).where(StoreGroup.id.in_(ids)))
            ).scalars()
        }
        if ids
        else {}
    )
    missing = [gid for gid in ids if gid not in groups]
    if missing:
        raise RaceValidationError("Группа точек не найдена")

    members: dict[UUID, list[UUID]] = {}  # store → groups
    if ids:
        rows = await session.execute(
            select(StoreGroupMember.store_id, StoreGroupMember.group_id)
            .join(Store, Store.id == StoreGroupMember.store_id)
            .where(StoreGroupMember.group_id.in_(ids), Store.archived_at.is_(None))
        )
        for store_id, group_id in rows:
            members.setdefault(store_id, []).append(group_id)
    overlaps = {s: g for s, g in members.items() if len(g) > 1}
    if overlaps:
        names = dict(
            (
                await session.execute(select(Store.id, Store.name).where(Store.id.in_(overlaps)))
            ).all()
        )
        first_store, first_groups = next(iter(sorted(overlaps.items(), key=lambda kv: str(kv[0]))))
        group_names = ", ".join(f"«{groups[g].name}»" for g in first_groups)
        raise RaceValidationError(
            f"Точка «{names.get(first_store, '?')}» состоит в нескольких лигах: {group_names}"
        )

    current = {
        lg.store_group_id: lg
        for lg in (
            await session.execute(
                select(RaceContestLeague).where(RaceContestLeague.contest_id == contest.id)
            )
        ).scalars()
    }
    league_by_group: dict[UUID, RaceContestLeague] = {}
    for pos, gid in enumerate(ids):
        lg = current.get(gid)
        if lg is None:
            lg = RaceContestLeague(
                tenant_id=contest.tenant_id,
                contest_id=contest.id,
                store_group_id=gid,
                name=groups[gid].name,
                position=pos,
            )
            session.add(lg)
        else:
            lg.name = groups[gid].name
            lg.position = pos
        league_by_group[gid] = lg
    for gid, lg in current.items():
        if gid not in league_by_group:
            await session.delete(lg)
    await session.flush()

    participants = list(
        (
            await session.execute(
                select(RaceParticipant).where(RaceParticipant.contest_id == contest.id)
            )
        ).scalars()
    )
    for p in participants:
        groups_of = members.get(p.store_id) or []
        p.league_id = league_by_group[groups_of[0]].id if groups_of else None
    await session.flush()


# ─── конкурс ────────────────────────────────────────────────────────────────


def _validate_shape(race_length_days: int, weeks_total: int, baseline_days: int) -> None:
    if race_length_days not in (7, 14):
        raise RaceValidationError("Длина заезда — 7 или 14 дней")
    if not 1 <= weeks_total <= 12:
        raise RaceValidationError("Длительность конкурса — от 1 до 12 недель")
    if (weeks_total * 7) % race_length_days != 0:
        raise RaceValidationError("Число недель должно делиться на длину заезда")
    if not 7 <= baseline_days <= 92:
        raise RaceValidationError("Ретро-период базы — от 7 до 92 дней")


async def create_contest(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    title: str,
    starts_on: date,
    race_length_days: int = 7,
    weeks_total: int = 4,
    baseline_mode: str = "contest",
    baseline_days: int = 28,
    league_group_ids: list[UUID] | None = None,
) -> RaceContest:
    _validate_shape(race_length_days, weeks_total, baseline_days)
    if baseline_mode not in ("contest", "race"):
        raise RaceValidationError("Режим базы — contest или race")
    contest = RaceContest(
        tenant_id=tenant_id,
        title=title.strip() or "Гусиная гонка",
        status="draft",
        starts_on=starts_on,
        ends_on=m.contest_ends_on(starts_on, weeks_total),
        race_length_days=race_length_days,
        weeks_total=weeks_total,
        baseline_mode=baseline_mode,
        baseline_days=baseline_days,
        created_by=actor_id,
    )
    session.add(contest)
    await session.flush()
    await materialize_participants(session, contest, actor_id=actor_id)
    await apply_leagues(session, contest, league_group_ids or [])
    audit.record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="create",
        object_type="race_contest",
        object_id=contest.id,
        object_label=contest.title,
    )
    return contest


async def update_contest(
    session: AsyncSession,
    contest: RaceContest,
    *,
    actor_id: UUID,
    title: str | None = None,
    starts_on: date | None = None,
    race_length_days: int | None = None,
    weeks_total: int | None = None,
    baseline_mode: str | None = None,
    baseline_days: int | None = None,
    league_group_ids: list[UUID] | None = None,
) -> RaceContest:
    if contest.status in ("finished", "cancelled"):
        raise RaceConflictError("Конкурс завершён — изменить нельзя")
    shape_changed = any(
        v is not None
        for v in (starts_on, race_length_days, weeks_total, baseline_mode, baseline_days)
    )
    if shape_changed and contest.status != "draft":
        raise RaceConflictError("Даты, длину заезда и режим базы можно менять только в черновике")
    if league_group_ids is not None and contest.status not in ("draft", "scheduled"):
        raise RaceConflictError("Лиги можно менять только до старта конкурса")
    diff: dict[str, Any] = {}
    if title is not None and title.strip() and title.strip() != contest.title:
        diff["title"] = {"old": contest.title, "new": title.strip()}
        contest.title = title.strip()
    if shape_changed:
        new_len = race_length_days or contest.race_length_days
        new_weeks = weeks_total or contest.weeks_total
        new_days = baseline_days or contest.baseline_days
        _validate_shape(new_len, new_weeks, new_days)
        if baseline_mode is not None and baseline_mode not in ("contest", "race"):
            raise RaceValidationError("Режим базы — contest или race")
        for name, value in (
            ("starts_on", starts_on),
            ("race_length_days", race_length_days),
            ("weeks_total", weeks_total),
            ("baseline_mode", baseline_mode),
            ("baseline_days", baseline_days),
        ):
            if value is not None and getattr(contest, name) != value:
                diff[name] = {"old": str(getattr(contest, name)), "new": str(value)}
                setattr(contest, name, value)
        contest.ends_on = m.contest_ends_on(contest.starts_on, contest.weeks_total)
    if league_group_ids is not None:
        await apply_leagues(session, contest, league_group_ids)
        diff["leagues"] = {"old": None, "new": [str(g) for g in league_group_ids]}
    contest.updated_at = _now()
    if diff:
        audit.record(
            session,
            tenant_id=contest.tenant_id,
            actor_id=actor_id,
            action="update",
            object_type="race_contest",
            object_id=contest.id,
            object_label=contest.title,
            diff=diff,
        )
    await session.flush()
    return contest


async def _overlapping_contest(session: AsyncSession, contest: RaceContest) -> RaceContest | None:
    return (
        (
            await session.execute(
                select(RaceContest).where(
                    RaceContest.tenant_id == contest.tenant_id,
                    RaceContest.id != contest.id,
                    RaceContest.status.in_(("scheduled", "active")),
                    RaceContest.starts_on <= contest.ends_on,
                    RaceContest.ends_on >= contest.starts_on,
                )
            )
        )
        .scalars()
        .first()
    )


@dataclass
class ScheduleReport:
    races: int
    needs_baseline_store_ids: list[UUID]
    baselines_computed: bool


async def schedule(
    session: AsyncSession,
    contest: RaceContest,
    *,
    today: date,
    actor_id: UUID,
    compute_baselines: Any | None = None,
) -> ScheduleReport:
    """Черновик → расписание: гонки, база первого заезда/конкурса, статус.

    `compute_baselines` — `iiko_pull.compute_baselines` или None (на staging
    iiko недоступен: все участники остаются `needs_baseline`, база вводится
    вручную).
    """
    if contest.status != "draft":
        raise RaceConflictError("Конкурс уже запланирован")
    if contest.starts_on < today:
        raise RaceValidationError("Дата старта уже прошла")
    other = await _overlapping_contest(session, contest)
    if other is not None:
        raise RaceConflictError(f"В эти даты уже идёт конкурс «{other.title}»")
    participants = await read.load_participants(session, contest)
    if not participants:
        raise RaceValidationError("Нет точек, привязанных к iiko — проверьте реестр объектов")

    spans = m.generate_races(contest.starts_on, contest.weeks_total, contest.race_length_days)
    for r in await read.load_races(session, contest):
        await session.delete(r)
    await session.flush()
    races = [
        Race(
            tenant_id=contest.tenant_id,
            contest_id=contest.id,
            seq=s.seq,
            starts_on=s.starts_on,
            ends_on=s.ends_on,
            status="scheduled",
        )
        for s in spans
    ]
    session.add_all(races)
    await session.flush()

    computed = False
    if compute_baselines is not None:
        target = races[0] if contest.baseline_mode == "race" else None
        await compute_baselines(session, contest=contest, race=target, set_by=actor_id)
        computed = True

    contest.status = "scheduled"
    contest.scheduled_at = _now()
    contest.updated_at = _now()
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="publish",
        object_type="race_contest",
        object_id=contest.id,
        object_label=contest.title,
        diff={"status": {"old": "draft", "new": "scheduled"}},
    )
    await session.flush()
    await activate_due(session, contest.tenant_id, today=today)

    baselines = await load_baselines(
        session, contest, races[0].id if contest.baseline_mode == "race" else None
    )
    missing = [
        p.store_id
        for p in participants
        if p.store_id not in baselines or baselines[p.store_id].value is None
    ]
    return ScheduleReport(
        races=len(races), needs_baseline_store_ids=missing, baselines_computed=computed
    )


async def activate_due(session: AsyncSession, tenant_id: UUID, *, today: date) -> None:
    """Запланированное со стартом ≤ сегодня становится активным (идемпотентно)."""
    active_exists = (
        await session.execute(
            select(func.count())
            .select_from(RaceContest)
            .where(RaceContest.tenant_id == tenant_id, RaceContest.status == "active")
        )
    ).scalar_one()
    due = list(
        (
            await session.execute(
                select(RaceContest)
                .where(
                    RaceContest.tenant_id == tenant_id,
                    RaceContest.status == "scheduled",
                    RaceContest.starts_on <= today,
                )
                .order_by(RaceContest.starts_on)
            )
        ).scalars()
    )
    for c in due:
        if active_exists:
            log.warning("race.activate_blocked_by_active", contest_id=str(c.id))
            break
        c.status = "active"
        c.updated_at = _now()
        active_exists = 1
    await session.flush()

    contests = list(
        (
            await session.execute(
                select(RaceContest).where(
                    RaceContest.tenant_id == tenant_id, RaceContest.status == "active"
                )
            )
        ).scalars()
    )
    for c in contests:
        races = await read.load_races(session, c)
        if any(r.status == "active" for r in races):
            continue
        for r in races:
            if r.status == "scheduled" and r.starts_on <= today:
                r.status = "active"
                break
    await session.flush()


# ─── закрытие дня и итоги ───────────────────────────────────────────────────


async def _write_snapshots(
    session: AsyncSession,
    contest: RaceContest,
    race: Race,
    days: list[date],
    participants: list[read.ParticipantInfo],
) -> int:
    if not days:
        return 0
    baselines = await load_baselines(session, contest, race.id)
    prev_max: dict[UUID, int | None] = {}
    for store_id, mx in (
        await session.execute(
            select(RaceSnapshot.store_id, func.max(RaceSnapshot.cells))
            .where(RaceSnapshot.race_id == race.id)
            .group_by(RaceSnapshot.store_id)
        )
    ).all():
        prev_max[store_id] = int(mx)
    written = 0
    for day in days:
        rows = await read.live_rows(
            session,
            contest,
            race,
            through_day=day,
            participants=participants,
            baselines=baselines,
        )
        for lr in rows:
            store_id = lr.rank.store_id
            record = m.is_record(lr.rank.cells, prev_max.get(store_id))
            session.add(
                RaceSnapshot(
                    tenant_id=contest.tenant_id,
                    race_id=race.id,
                    store_id=store_id,
                    day=day,
                    receipts_cum=lr.receipts,
                    items_cum=lr.items,
                    avg=lr.rank.avg,
                    base=lr.base,
                    pct=lr.rank.pct,
                    cells=lr.rank.cells,
                    needs_baseline=lr.rank.needs_baseline,
                    is_record=record,
                )
            )
            prev = prev_max.get(store_id)
            prev_max[store_id] = lr.rank.cells if prev is None else max(prev, lr.rank.cells)
            written += 1
        await session.flush()
    return written


async def finish_race(
    session: AsyncSession,
    contest: RaceContest,
    race: Race,
    *,
    through_day: date,
    reason: str,
    actor_id: UUID | None = None,
) -> list[RaceResult]:
    """Заморозить итоги заезда по данным до `through_day` включительно."""
    if race.status == "finished":
        return await read.frozen_results(session, race)
    participants = await read.load_participants(session, contest)
    baselines = await load_baselines(session, contest, race.id)
    rows = await read.live_rows(
        session,
        contest,
        race,
        through_day=through_day,
        participants=participants,
        baselines=baselines,
    )
    ranked = m.rank([lr.rank for lr in rows])
    by_store = {lr.rank.store_id: lr for lr in rows}
    dept = {p.store_id: p.department_id for p in participants}
    league = {p.store_id: p.league_id for p in participants}
    results: list[RaceResult] = []
    for rr in ranked:
        lr = by_store[rr.store_id]
        results.append(
            RaceResult(
                tenant_id=contest.tenant_id,
                race_id=race.id,
                store_id=rr.store_id,
                department_id=dept[rr.store_id],
                league_id=league[rr.store_id],
                base=lr.base,
                receipts=lr.receipts,
                items=lr.items,
                avg=rr.avg,
                pct=rr.pct,
                cells=rr.cells,
                needs_baseline=rr.needs_baseline,
                place=rr.place,
                place_in_league=rr.place_in_league,
            )
        )
    session.add_all(results)
    race.status = "finished"
    race.finished_at = _now()
    race.finish_reason = reason
    if reason == "forced":
        race.forced_by = actor_id
        race.ends_on = through_day
    await session.flush()
    log.info(
        "race.finished",
        contest_id=str(contest.id),
        race_id=str(race.id),
        seq=race.seq,
        reason=reason,
        through=str(through_day),
    )
    return results


@dataclass
class CloseReport:
    snapshots: int = 0
    finished_race_ids: list[UUID] = field(default_factory=list)
    activated_race_ids: list[UUID] = field(default_factory=list)
    contest_finished: bool = False
    # Заезды, которым нужна база (режим `race`) — считает ВЫЗЫВАЮЩИЙ после
    # commit'а, вне advisory-лока: расчёт ходит в iiko.
    races_needing_baseline: list[UUID] = field(default_factory=list)


async def close_day(session: AsyncSession, contest: RaceContest, *, close_day: date) -> CloseReport:
    """Ночное закрытие: снимки за пропущенные дни, итоги заезда по `ends_on`,
    следующий заезд. Идемпотентно — повторный вызов ничего не дописывает."""
    await lock_tenant(session, contest.tenant_id)
    report = CloseReport()
    races = await read.load_races(session, contest)
    participants = await read.load_participants(session, contest)
    active = [r for r in races if r.status == "active"]
    for race in active:
        last_day = (
            await session.execute(
                select(func.max(RaceSnapshot.day)).where(RaceSnapshot.race_id == race.id)
            )
        ).scalar_one()
        days = m.pending_snapshot_days(race.starts_on, race.ends_on, last_day, close_day)
        report.snapshots += await _write_snapshots(session, contest, race, days, participants)
        if race.ends_on <= close_day:
            await finish_race(session, contest, race, through_day=race.ends_on, reason="schedule")
            report.finished_race_ids.append(race.id)
            if not any(r.seq > race.seq for r in races):
                contest.status = "finished"
                contest.finished_at = _now()
                report.contest_finished = True
    await session.flush()
    if contest.baseline_mode == "race":
        # База следующего заезда — ОБЩИМ правилом по датам, а не веткой
        # завершения: одно условие покрывает смену заездов по расписанию,
        # пробел после досрочного завершения (`force_finish` базу не
        # считает) и старт «завтра» из `start_early`. Ночь, когда iiko был
        # занят, догоняется следующей — условие остаётся истинным.
        due_by = close_day + timedelta(days=1)
        for r in races:
            if r.status == "finished" or r.starts_on > due_by:
                continue
            if not await has_iiko_baseline(session, r.id):
                report.races_needing_baseline.append(r.id)
    before = {r.id for r in races if r.status == "active"}
    await activate_due(session, contest.tenant_id, today=close_day + timedelta(days=1))
    after = {r.id for r in await read.load_races(session, contest) if r.status == "active"}
    report.activated_race_ids = sorted(after - before, key=str)
    return report


async def force_finish(
    session: AsyncSession,
    contest: RaceContest,
    race: Race,
    *,
    today: date,
    actor_id: UUID,
    pull: Any | None = None,
) -> tuple[list[RaceResult], bool]:
    """Завершить активный заезд сегодняшним днём; следующие заезды не сдвигаются."""
    if race.status != "active":
        raise RaceConflictError("Заезд не активен")
    pull_ok = True
    if pull is not None:
        try:
            await pull(
                session,
                tenant_id=contest.tenant_id,
                day_from=today - timedelta(days=1),
                day_to=today,
            )
        except Exception as e:  # noqa: BLE001 — итоги фиксируем по тому, что есть
            log.warning("race.force_finish_pull_failed", err=str(e))
            pull_ok = False
    await lock_tenant(session, contest.tenant_id)
    through = min(today, race.ends_on)
    participants = await read.load_participants(session, contest)
    last_day = (
        await session.execute(
            select(func.max(RaceSnapshot.day)).where(RaceSnapshot.race_id == race.id)
        )
    ).scalar_one()
    days = m.pending_snapshot_days(race.starts_on, through, last_day, through)
    await _write_snapshots(session, contest, race, days, participants)
    results = await finish_race(
        session, contest, race, through_day=through, reason="forced", actor_id=actor_id
    )
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="update",
        object_type="race",
        object_id=race.id,
        object_label=f"{contest.title} · заезд {race.seq}",
        diff={
            "status": {"old": "active", "new": "finished"},
            "finish_reason": {"old": None, "new": "forced"},
        },
    )
    races = await read.load_races(session, contest)
    if not any(r.seq > race.seq for r in races):
        contest.status = "finished"
        contest.finished_at = _now()
    await activate_due(session, contest.tenant_id, today=today)
    return results, pull_ok


@dataclass
class StartReport:
    race_id: UUID
    starts_on: date
    activated: bool
    baselines_computed: bool
    needs_baseline_store_ids: list[UUID]


async def start_early(
    session: AsyncSession,
    contest: RaceContest,
    race: Race,
    *,
    today: date,
    actor_id: UUID,
    compute_baselines: Any | None = None,
) -> StartReport:
    """Начать запланированный заезд раньше расписания — сегодня или завтра.

    Правила (решение владельца 19.09): день атомарен — не раньше дня после
    `ends_on` предыдущего заезда (`m.early_start_day`); `ends_on` не двигается —
    даты объявлены, заезд просто становится длиннее; в режиме `race` при старте
    «сегодня» база считается здесь же из iiko, при «завтра» — ночной джобой по
    общему правилу `close_day`. Дата ставится ДО расчёта: `compute_baselines`
    берёт якорь ретро-окна из `race.starts_on`. Лок — после похода в iiko.
    """
    if contest.status != "active":
        raise RaceConflictError("Конкурс не активен")
    if race.status != "scheduled":
        raise RaceConflictError("Заезд уже стартовал")
    races = await read.load_races(session, contest)
    candidate = m.early_start_candidate(races, today)
    if candidate is None or candidate[0].id != race.id:
        if any(r.status == "active" for r in races):
            raise RaceConflictError("Сначала завершите текущий заезд")
        raise RaceConflictError(f"Заезд и так стартует {fmt_day(race.starts_on)}")
    day = candidate[1]
    old_start = race.starts_on
    race.starts_on = day
    await session.flush()
    computed = False
    if (
        day == today
        and contest.baseline_mode == "race"
        and compute_baselines is not None
        and not await has_iiko_baseline(session, race.id)
    ):
        await compute_baselines(session, contest=contest, race=race, set_by=actor_id)
        computed = True
    await lock_tenant(session, contest.tenant_id)
    # Два админа одновременно: второй дожидается лока и видит уже активный заезд.
    await session.refresh(race)
    if race.status != "scheduled":
        raise RaceConflictError("Заезд уже стартовал")
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="update",
        object_type="race",
        object_id=race.id,
        object_label=f"{contest.title} · заезд {race.seq}",
        diff={"starts_on": {"old": old_start.isoformat(), "new": day.isoformat()}},
    )
    await session.flush()
    await activate_due(session, contest.tenant_id, today=today)
    await session.refresh(race)
    missing: list[UUID] = []
    if contest.baseline_mode == "race" and day == today:
        participants = await read.load_participants(session, contest)
        baselines = await load_baselines(session, contest, race.id)
        missing = [
            p.store_id
            for p in participants
            if p.store_id not in baselines or baselines[p.store_id].value is None
        ]
    log.info(
        "race.started_early",
        contest_id=str(contest.id),
        race_id=str(race.id),
        seq=race.seq,
        starts_on=str(day),
        activated=race.status == "active",
        baselines_computed=computed,
    )
    return StartReport(
        race_id=race.id,
        starts_on=day,
        activated=race.status == "active",
        baselines_computed=computed,
        needs_baseline_store_ids=missing,
    )


async def cancel_contest(
    session: AsyncSession, contest: RaceContest, *, today: date, actor_id: UUID
) -> None:
    if contest.status in ("finished", "cancelled"):
        raise RaceConflictError("Конкурс уже завершён")
    await lock_tenant(session, contest.tenant_id)
    for race in await read.load_races(session, contest):
        if race.status == "active":
            await finish_race(
                session,
                contest,
                race,
                through_day=min(today, race.ends_on),
                reason="forced",
                actor_id=actor_id,
            )
    contest.status = "cancelled"
    contest.cancelled_at = _now()
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="archive",
        object_type="race_contest",
        object_id=contest.id,
        object_label=contest.title,
    )
    await session.flush()


# ─── база и участники (админ) ───────────────────────────────────────────────


async def set_baseline(
    session: AsyncSession,
    contest: RaceContest,
    *,
    store_id: UUID,
    race_id: UUID | None,
    value: float | None,
    note: str | None,
    actor_id: UUID,
) -> RaceBaseline | None:
    """Ручная база; `value=None` снимает ручную правку (остаётся iiko-строка,
    если была, иначе — «нужна настройка»)."""
    if value is not None and value <= 0:
        raise RaceValidationError("База должна быть больше нуля")
    store_name = (
        await session.execute(select(Store.name).where(Store.id == store_id))
    ).scalar_one_or_none() or "?"
    current = await get_baseline_row(session, contest.id, store_id, race_id)
    old = None if current is None else (None if current.value is None else float(current.value))
    old_source = None if current is None else current.source
    if value is None:
        if current is not None and current.source == "manual":
            await session.delete(current)
            await session.flush()
        audit.record(
            session,
            tenant_id=contest.tenant_id,
            actor_id=actor_id,
            action="update",
            object_type="race_baseline",
            object_id=store_id,
            object_label=store_name,
            diff={"value": {"old": old, "new": None}, "source": {"old": old_source, "new": None}},
        )
        return None
    row = await upsert_baseline(
        session,
        contest=contest,
        store_id=store_id,
        race_id=race_id,
        value=value,
        source="manual",
        note=note,
        set_by=actor_id,
    )
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="update",
        object_type="race_baseline",
        object_id=store_id,
        object_label=store_name,
        diff={"value": {"old": old, "new": value}, "source": {"old": old_source, "new": "manual"}},
    )
    return row


async def set_participant(
    session: AsyncSession,
    contest: RaceContest,
    *,
    store_id: UUID,
    included: bool,
    actor_id: UUID,
) -> UUID | None:
    """Включить/выключить точку; включение вытесняет двойника по подразделению.
    → store_id вытесненного двойника или None."""
    if contest.status in ("finished", "cancelled"):
        raise RaceConflictError("Конкурс завершён — состав изменить нельзя")
    row = (
        await session.execute(
            select(RaceParticipant).where(
                RaceParticipant.contest_id == contest.id, RaceParticipant.store_id == store_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise RaceValidationError("Точка не участвует в конкурсе")
    replaced: UUID | None = None
    if included and row.excluded_at is not None:
        twin = (
            await session.execute(
                select(RaceParticipant).where(
                    RaceParticipant.contest_id == contest.id,
                    RaceParticipant.department_id == row.department_id,
                    RaceParticipant.excluded_at.is_(None),
                    RaceParticipant.store_id != store_id,
                )
            )
        ).scalar_one_or_none()
        if twin is not None:
            twin.excluded_at = _now()
            twin.excluded_by = actor_id
            twin.exclude_reason = "duplicate"
            replaced = twin.store_id
            await session.flush()
        row.excluded_at = None
        row.excluded_by = None
        row.exclude_reason = None
    elif not included and row.excluded_at is None:
        row.excluded_at = _now()
        row.excluded_by = actor_id
        row.exclude_reason = "manual"
    await session.flush()
    audit.record(
        session,
        tenant_id=contest.tenant_id,
        actor_id=actor_id,
        action="update",
        object_type="race_participant",
        object_id=store_id,
        object_label=contest.title,
        diff={"included": {"old": not included, "new": included}},
    )
    return replaced


# ─── уведомления ────────────────────────────────────────────────────────────


async def _recipients(session: AsyncSession, store_ids: list[UUID]) -> list[UUID]:
    if not store_ids:
        return []
    rows = await session.execute(
        select(EmployeeProfile.employee_id).where(
            learning_population_filter(),
            EmployeeProfile.employee_id.is_not(None),
            EmployeeProfile.store_id.in_(store_ids),
        )
    )
    return [r[0] for r in rows]


async def send_pending_notifications(
    tenant_id: UUID, *, now: datetime, session_factory: Any = tenant_scoped_session
) -> int:
    """Пуши «заезд стартовал» и «рекорд» — не раньше 09:00 MSK, метки дедупа
    коммитятся ДО отправки (иначе откат = повторная рассылка всей сети)."""
    if not gate.sync_enabled():
        return 0
    if now.astimezone(display_tz()).hour < NOTIFY_FROM_HOUR:
        return 0
    batches: list[PushBatch] = []
    sent = 0
    async with session_factory(tenant_id) as session:
        if not await gate.race_enabled_for(session, tenant_id):
            return 0
        contests = {
            c.id: c
            for c in (
                await session.execute(
                    select(RaceContest).where(
                        RaceContest.tenant_id == tenant_id, RaceContest.status == "active"
                    )
                )
            ).scalars()
        }
        if not contests:
            return 0
        # заезд стартовал
        claimed = list(
            (
                await session.execute(
                    update(Race)
                    .where(
                        Race.contest_id.in_(contests),
                        Race.status == "active",
                        Race.started_notified_at.is_(None),
                    )
                    .values(started_notified_at=now)
                    .returning(Race)
                )
            ).scalars()
        )
        for race in claimed:
            contest = contests[race.contest_id]
            participants = await read.load_participants(session, contest)
            recipients = await _recipients(session, [p.store_id for p in participants])
            total = contest.weeks_total * 7 // contest.race_length_days
            _n, batch = await queue_many(
                session,
                tenant_id=tenant_id,
                employee_ids=recipients,
                kind=KIND_STARTED,
                title=f"Гусиная гонка: заезд {race.seq} стартовал",
                body=(
                    f"{contest.title} — заезд {race.seq} из {total}, "
                    f"{fmt_day_range(race.starts_on, race.ends_on)}. "
                    "Все гуси на старте — база = 100 клеток."
                ),
                url="/learn/race",
                payload={
                    "contest_id": str(contest.id),
                    "race_id": str(race.id),
                    "seq": race.seq,
                },
            )
            if batch is not None:
                batches.append(batch)
            sent += len(recipients)
        # рекорд: по одной точке — только последний день, старые записи гасим
        pending = list(
            (
                await session.execute(
                    select(RaceSnapshot)
                    .join(Race, Race.id == RaceSnapshot.race_id)
                    .where(
                        Race.contest_id.in_(contests),
                        RaceSnapshot.is_record.is_(True),
                        RaceSnapshot.record_notified_at.is_(None),
                    )
                    .order_by(RaceSnapshot.store_id, RaceSnapshot.day.desc())
                )
            ).scalars()
        )
        latest: dict[tuple[UUID, UUID], RaceSnapshot] = {}
        for snap in pending:
            latest.setdefault((snap.race_id, snap.store_id), snap)
            snap.record_notified_at = now
        if latest:
            race_by_id = {
                r.id: r
                for r in (
                    await session.execute(select(Race).where(Race.id.in_({k[0] for k in latest})))
                ).scalars()
            }
            names = {
                sid: (name, code)
                for sid, name, code in (
                    await session.execute(
                        select(Store.id, Store.name, Store.code).where(
                            Store.id.in_({k[1] for k in latest})
                        )
                    )
                ).all()
            }
            for (race_id, store_id), snap in latest.items():
                race = race_by_id[race_id]
                name, code = names.get(store_id, ("точка", None))
                recipients = await _recipients(session, [store_id])
                pct = float(snap.pct) if snap.pct is not None else 0.0
                _n, batch = await queue_many(
                    session,
                    tenant_id=tenant_id,
                    employee_ids=recipients,
                    kind=KIND_RECORD,
                    title=f"Рекорд заезда: {code or name}",
                    body=(
                        f"Вчера «{name}» вышла на {int(snap.cells)} клеток ({pct:+.1f} %) — "
                        f"лучший результат в заезде {race.seq}."
                    ),
                    url=f"/learn/race?store={store_id}",
                    payload={
                        "race_id": str(race_id),
                        "store_id": str(store_id),
                        "day": snap.day.isoformat(),
                    },
                )
                if batch is not None:
                    batches.append(batch)
                sent += len(recipients)
        await session.commit()
    for batch in batches:
        schedule_push_batch(batch)
    return sent
