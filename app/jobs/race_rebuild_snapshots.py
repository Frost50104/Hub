"""Разовый ремонт ночных снимков гонки после отказа iiko.

До 17.10 ночное закрытие писало `race_snapshots` даже когда выгрузка падала:
14–17.10 iiko отклонял логин, и три снимка подряд (14, 15, 16.10) оказались
копией неполного 14.10. После дотяжки суточных данных снимки сами не
перепишутся — закрытие дописывает только дни ПОСЛЕ последнего снимка. Эта
джоба удаляет снимки окна и пишет их заново тем же кодом, что ночное
закрытие (`engine.rebuild_snapshots` → `_write_snapshots`).

Сторожа живут в `engine.rebuild_snapshots`: заезд активен (итоги завершённого
заморожены), окно — закрытые дни от старта заезда по вчера, конец окна =
последний снимок заезда. Сама джоба дополнительно требует суточных данных в
каждом дне окна: снимки «без данных» — ровно то, что чиним.

Без `--apply` — честный разбор: расчёт выполняется и откатывается, «после»
печатается по реальным числам. `record_notified_at` переписанных строк пуст —
рекорды уйдут ближайшим тиком ≥ 09:00 как обычные (решение владельца 17.10);
повторный `--apply` разошлёт их снова. В iiko джоба не ходит — работает и на
staging (`race_sync_enabled=false`). Запуск на сервере, как у остальных джоб:

    systemd-run --wait --pipe --uid=signaris \\
      -p EnvironmentFile=/opt/signaris-hub/.env -p WorkingDirectory=/opt/signaris-hub \\
      /opt/signaris-hub/.venv/bin/python -m app.jobs.race_rebuild_snapshots \\
      --tenant uppetit --from 2026-10-14 --to 2026-10-16 [--contest <uuid>] [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select

from app import log as log_config
from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.race import RaceContest, RaceDailyStat, RaceSnapshot
from app.models.shadow import ShadowTenant
from app.services.race import engine, read

log = structlog.get_logger("jobs.race_rebuild_snapshots")

DayStats = tuple[int, int, int, int]  # строк, Σ клеток, max клеток, рекордов


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


async def _tenant_id(slug: str) -> UUID | None:
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        return (
            await db.execute(select(ShadowTenant.id).where(ShadowTenant.slug == slug))
        ).scalar_one_or_none()


async def _coverage(session, departments: list[str], days: list[date]) -> dict[date, int]:
    """день → число подразделений участников с суточными данными iiko."""
    rows = await session.execute(
        select(RaceDailyStat.day, func.count(func.distinct(RaceDailyStat.department_id)))
        .where(RaceDailyStat.department_id.in_(departments), RaceDailyStat.day.in_(days))
        .group_by(RaceDailyStat.day)
    )
    return {d: int(n) for d, n in rows}


async def _per_day(session, race_id: UUID, store_ids: list[UUID], days: list[date]):
    rows = await session.execute(
        select(
            RaceSnapshot.day,
            func.count(),
            func.coalesce(func.sum(RaceSnapshot.cells), 0),
            func.coalesce(func.max(RaceSnapshot.cells), 0),
            func.count().filter(RaceSnapshot.is_record.is_(True)),
        )
        .where(
            RaceSnapshot.race_id == race_id,
            RaceSnapshot.store_id.in_(store_ids),
            RaceSnapshot.day.in_(days),
        )
        .group_by(RaceSnapshot.day)
    )
    return {d: (int(n), int(s), int(mx), int(r)) for d, n, s, mx, r in rows}


async def _cells(session, race_id: UUID, store_ids: list[UUID], days: list[date]):
    rows = await session.execute(
        select(
            RaceSnapshot.store_id, RaceSnapshot.day, RaceSnapshot.cells, RaceSnapshot.is_record
        ).where(
            RaceSnapshot.race_id == race_id,
            RaceSnapshot.store_id.in_(store_ids),
            RaceSnapshot.day.in_(days),
        )
    )
    return {(sid, d): (int(c), bool(r)) for sid, d, c, r in rows}


def _table(title: str, per_day: dict[date, DayStats], days: list[date]) -> None:
    _say(title)
    for d in days:
        n, s, mx, r = per_day.get(d, (0, 0, 0, 0))
        _say(f"  {d}  строк {n:3d}  Σ клеток {s:5d}  max {mx:3d}  рекордов {r}")


async def main() -> int:  # noqa: C901 — линейный сценарий с печатью отчёта
    log_config.configure()
    parser = argparse.ArgumentParser(description="Переписать ночные снимки гонки за окно дней")
    parser.add_argument("--tenant", required=True, help="slug организации (например uppetit)")
    parser.add_argument(
        "--from", dest="day_from", required=True, type=date.fromisoformat, help="первый день окна"
    )
    parser.add_argument(
        "--to",
        dest="day_to",
        required=True,
        type=date.fromisoformat,
        help="последний день окна — обязан быть последним снимком заезда",
    )
    parser.add_argument("--contest", help="id конкурса; по умолчанию — текущий активный")
    parser.add_argument(
        "--apply", action="store_true", help="записать (по умолчанию — расчёт и откат)"
    )
    args = parser.parse_args()

    if not get_settings().race_enabled:
        _say("модуль гонки выключен (SIGNARIS_HUB_RACE_ENABLED)")
        return 2
    tenant_id = await _tenant_id(args.tenant)
    if tenant_id is None:
        _say(f"организация «{args.tenant}» не найдена")
        return 2
    if args.day_to < args.day_from:
        _say("конец окна раньше начала")
        return 4
    days = [
        args.day_from + timedelta(days=i) for i in range((args.day_to - args.day_from).days + 1)
    ]
    today = engine.today_local()

    async with tenant_scoped_session(tenant_id) as session:
        contest = (
            await session.get(RaceContest, UUID(args.contest))
            if args.contest
            else await read.current_contest(session, tenant_id)
        )
        if contest is None or contest.status != "active":
            _say("активного конкурса нет: передайте --contest активного конкурса")
            return 3
        active = [r for r in await read.load_races(session, contest) if r.status == "active"]
        if len(active) != 1:
            _say(f"активных заездов у конкурса: {len(active)} — переписывать нечего")
            return 3
        race = active[0]
        participants = await read.load_participants(session, contest)
        store_ids = [p.store_id for p in participants]
        names = {p.store_id: p.name for p in participants}
        _say(
            f"конкурс: «{contest.title}» · заезд №{race.seq} · {race.starts_on} — {race.ends_on}"
            f" · живых участников {len(store_ids)} · сегодня {today}"
        )
        coverage = await _coverage(session, [p.department_id for p in participants], days)
        _say("суточные данные iiko в окне (подразделений с данными / участников):")
        missing: list[date] = []
        for d in days:
            n = coverage.get(d, 0)
            _say(f"  {d}  {n:3d} / {len(store_ids)}")
            if n == 0:
                missing.append(d)
        if missing:
            _say(
                f"нет суточных данных за {', '.join(map(str, missing))} — сначала дотяните "
                "выгрузку (POST /learn/race/admin/sync с day_from/day_to)"
            )
            return 4

        before = await _cells(session, race.id, store_ids, days)
        _table("до:", await _per_day(session, race.id, store_ids, days), days)
        try:
            report = await engine.rebuild_snapshots(
                session, contest, race, day_from=args.day_from, day_to=args.day_to, today=today
            )
        except (engine.RaceValidationError, engine.RaceConflictError) as e:
            await session.rollback()
            _say(f"отказ: {e}")
            return 4
        after = await _cells(session, race.id, store_ids, days)
        _table("после:", await _per_day(session, race.id, store_ids, days), days)
        changed = 0
        for sid in store_ids:
            diffs = []
            for d in days:
                old, new = before.get((sid, d)), after.get((sid, d))
                if old == new:
                    continue
                star = " ★" if new is not None and new[1] else ""
                diffs.append(
                    f"{d.day:02d}: {old[0] if old else '—'} → {new[0] if new else '—'}{star}"
                )
            if diffs:
                changed += 1
                _say(f"  {names[sid]}: " + ", ".join(diffs))
        pushes = len({sid for (sid, _d), (_c, rec) in after.items() if rec})
        _say(
            f"точек с изменениями: {changed}; удалено {report.deleted}, оставлено строк "
            f"исключённых точек {report.kept_excluded}, записано {report.written}; "
            f"рекордов {report.records_before} → {report.records_after}; "
            f"пушей «рекорд» уйдёт ближайшим тиком ≥ 09:00 МСК: {pushes}"
        )
        log.info(
            "race_rebuild_snapshots.plan",
            tenant=args.tenant,
            contest_id=str(contest.id),
            race_id=str(race.id),
            day_from=str(args.day_from),
            day_to=str(args.day_to),
            deleted=report.deleted,
            written=report.written,
            records_before=report.records_before,
            records_after=report.records_after,
            apply=args.apply,
        )
        if not args.apply:
            await session.rollback()
            _say("разбор — расчёт откачен; повторите с --apply, чтобы записать")
            return 0
        await session.commit()
        _say("записано")
        log.info("race_rebuild_snapshots.applied", race_id=str(race.id), written=report.written)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
