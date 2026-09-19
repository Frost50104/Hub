"""Закрытие дня: снимки с догоном, рекорды, заморозка итогов, следующий заезд."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.race import RaceDailyStat, RaceResult, RaceSnapshot
from app.services.race import engine, read
from app.services.race.baselines import upsert_baseline
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


# Роль testcontainers — суперюзер и RLS не режет: `materialize_participants`
# читает `stores` без ручного tenant-фильтра (в проде скоупит RLS) и под
# суперюзером видел бы магазины соседних тестов. Поэтому — реальная app-роль.
@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


D0 = date(2026, 6, 1)


def _day(n: int) -> date:
    return D0 + timedelta(days=n)


async def _stat(db, tenant_id, dept, day, receipts, items):
    db.add(
        RaceDailyStat(
            tenant_id=tenant_id,
            department_id=dept,
            day=day,
            receipts=receipts,
            items=items,
            pulled_at=datetime.now(UTC),
        )
    )
    await db.flush()


async def _scheduled_contest(db, net, **kw):
    contest = await engine.create_contest(
        db,
        tenant_id=net.A.tenant_id,
        actor_id=net.admin.employee_id,
        title="Тест",
        starts_on=D0,
        league_group_ids=[net.g1.id, net.g2.id],
        **kw,
    )
    await engine.schedule(
        db, contest, today=D0, actor_id=net.admin.employee_id, compute_baselines=None
    )
    for store in (net.A, net.C):
        await engine.set_baseline(
            db,
            contest,
            store_id=store.id,
            race_id=None,
            value=2.0,
            note=None,
            actor_id=net.admin.employee_id,
        )
    return contest


async def _snaps(db, race_id, store_id):
    rows = await db.execute(
        select(RaceSnapshot)
        .where(RaceSnapshot.race_id == race_id, RaceSnapshot.store_id == store_id)
        .order_by(RaceSnapshot.day)
    )
    return list(rows.scalars())


async def test_close_day_catches_up_marks_records_and_freezes_results(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=1)  # один заезд D0..D6
    race = (await read.load_races(db, contest))[0]
    await _stat(db, tenant_id, "dep-1", _day(0), 100, 220)  # 2,2 → 110
    await _stat(db, tenant_id, "dep-1", _day(1), 100, 300)  # cum 2,6 → 130
    await _stat(db, tenant_id, "dep-1", _day(2), 100, 150)  # cum 2,233 → 112
    for n in range(0, 7):
        await _stat(db, tenant_id, "dep-2", _day(n), 100, 200)  # ровно база → 100

    r0 = await engine.close_day(db, contest, close_day=_day(0))
    assert r0.snapshots == 2 and not r0.finished_race_ids
    a0 = await _snaps(db, race.id, net.A.id)
    assert [(s.day, int(s.cells), s.is_record) for s in a0] == [(_day(0), 110, False)]

    # ночь D1 пропущена — закрытие D2 догоняет обе
    r2 = await engine.close_day(db, contest, close_day=_day(2))
    assert r2.snapshots == 4
    a = await _snaps(db, race.id, net.A.id)
    assert [(s.day, int(s.cells), s.is_record) for s in a] == [
        (_day(0), 110, False),
        (_day(1), 130, True),
        (_day(2), 112, False),
    ]
    c = await _snaps(db, race.id, net.C.id)
    assert all(int(s.cells) == 100 and not s.is_record for s in c), "на старте рекорда нет"

    for n in range(3, 7):
        await _stat(db, tenant_id, "dep-1", _day(n), 100, 300)
    r6 = await engine.close_day(db, contest, close_day=_day(6))
    assert r6.finished_race_ids == [race.id] and r6.contest_finished
    results = {
        r.store_id: r
        for r in (
            await db.execute(select(RaceResult).where(RaceResult.race_id == race.id))
        ).scalars()
    }
    assert results[net.A.id].place == 1 and results[net.C.id].place == 2
    assert int(results[net.A.id].cells) == 134  # 1870 позиций / 700 чеков = 2,671 → 133,6
    await db.refresh(race)
    assert race.status == "finished" and race.finish_reason == "schedule"
    assert contest.status == "finished"

    # правка статистики после заморозки итогов не трогает
    await _stat(db, tenant_id, "dep-1", _day(7), 1000, 9000)
    again = await engine.close_day(db, contest, close_day=_day(7))
    assert again.snapshots == 0 and not again.finished_race_ids
    frozen = (
        (await db.execute(select(RaceResult).where(RaceResult.race_id == race.id))).scalars().all()
    )
    assert len(frozen) == 2 and {int(r.cells) for r in frozen} == {
        int(results[net.A.id].cells),
        100,
    }


async def test_next_race_activates_and_race_mode_requests_baseline(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=2, baseline_mode="race")
    races = await read.load_races(db, contest)
    assert len(races) == 2
    report = await engine.close_day(db, contest, close_day=_day(6))
    assert report.finished_race_ids == [races[0].id]
    assert report.races_needing_baseline == [races[1].id]
    await db.refresh(races[1])
    assert races[1].status == "active", "стартует днём после закрытия первого"
    assert contest.status == "active"


async def test_force_finish_freezes_today_and_keeps_later_dates(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    races = await read.load_races(db, contest)
    await _stat(db, tenant_id, "dep-1", _day(1), 50, 150)
    results, pull_ok = await engine.force_finish(
        db, contest, races[0], today=_day(2), actor_id=net.admin.employee_id, pull=None
    )
    assert pull_ok is True and len(results) == 2
    await db.refresh(races[0])
    assert races[0].status == "finished" and races[0].finish_reason == "forced"
    assert races[0].ends_on == _day(2)
    await db.refresh(races[1])
    assert races[1].starts_on == _day(7) and races[1].status == "scheduled", "даты не сдвигаются"
    with pytest.raises(engine.RaceConflictError):
        await engine.force_finish(
            db, contest, races[0], today=_day(2), actor_id=net.admin.employee_id, pull=None
        )


# ─── ранний старт заезда ────────────────────────────────────────────────────


async def _force_finish_first(db, net, contest, *, today):
    races = await read.load_races(db, contest)
    await engine.force_finish(
        db, contest, races[0], today=today, actor_id=net.admin.employee_id, pull=None
    )
    return races


async def test_start_early_today_after_forced_finish_keeps_end_and_audits(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    races = await _force_finish_first(db, net, contest, today=_day(2))
    report = await engine.start_early(
        db, contest, races[1], today=_day(3), actor_id=net.admin.employee_id
    )
    await db.refresh(races[1])
    assert report.activated is True and races[1].status == "active"
    assert races[1].starts_on == _day(3) and races[1].ends_on == _day(13), "конец не двигается"
    assert races[1].started_notified_at is None, "пуш «стартовал» уйдёт часовой джобой"
    assert report.baselines_computed is False and report.needs_baseline_store_ids == []
    entry = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_type == "race", AuditLog.object_id == races[1].id
            )
        )
    ).scalar_one()
    assert entry.diff == {"starts_on": {"old": str(_day(7)), "new": str(_day(3))}}
    from app.services.race import math as m

    assert m.early_start_candidate(await read.load_races(db, contest), _day(3)) is None


async def test_start_early_on_finish_day_means_tomorrow_and_night_activates(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, baseline_mode="race")
    races = await _force_finish_first(db, net, contest, today=_day(2))
    report = await engine.start_early(
        db, contest, races[1], today=_day(2), actor_id=net.admin.employee_id
    )
    await db.refresh(races[1])
    assert report.activated is False and report.starts_on == _day(3)
    assert races[1].status == "scheduled" and races[1].starts_on == _day(3), "день атомарен"
    close = await engine.close_day(db, contest, close_day=_day(2))
    await db.refresh(races[1])
    assert races[1].status == "active" and close.activated_race_ids == [races[1].id]
    assert close.races_needing_baseline == [races[1].id], "база — ночной джобой по общему правилу"


async def test_start_early_conflicts(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    races = await read.load_races(db, contest)
    with pytest.raises(engine.RaceConflictError, match="Сначала завершите"):
        await engine.start_early(
            db, contest, races[1], today=_day(2), actor_id=net.admin.employee_id
        )
    await _force_finish_first(db, net, contest, today=_day(6))
    with pytest.raises(engine.RaceConflictError, match="и так стартует"):
        await engine.start_early(
            db, contest, races[1], today=_day(6), actor_id=net.admin.employee_id
        )
    with pytest.raises(engine.RaceConflictError, match="и так стартует"):
        await engine.start_early(
            db, contest, races[2], today=_day(6), actor_id=net.admin.employee_id
        )
    with pytest.raises(engine.RaceConflictError, match="уже стартовал"):
        await engine.start_early(
            db, contest, races[0], today=_day(6), actor_id=net.admin.employee_id
        )


async def test_close_day_requests_next_baseline_after_forced_finish(db: AsyncSession, tenant_id):
    """Регресс пробела: `force_finish` базу следующего заезда не считает, и
    ветка завершения в `close_day` до него не доходила — теперь правило общее."""
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, baseline_mode="race")
    races = await _force_finish_first(db, net, contest, today=_day(2))
    assert (await engine.close_day(db, contest, close_day=_day(5))).races_needing_baseline == []
    assert (await engine.close_day(db, contest, close_day=_day(6))).races_needing_baseline == [
        races[1].id
    ]
    await upsert_baseline(
        db, contest=contest, store_id=net.A.id, race_id=races[1].id, value=2.1, source="iiko"
    )
    assert (await engine.close_day(db, contest, close_day=_day(6))).races_needing_baseline == []


async def test_start_early_sets_date_before_computing_baseline(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, baseline_mode="race")
    races = await _force_finish_first(db, net, contest, today=_day(2))
    seen: list[date] = []

    async def stub(session, *, contest, race, set_by=None):  # noqa: ARG001
        seen.append(race.starts_on)

    report = await engine.start_early(
        db, contest, races[1], today=_day(3), actor_id=net.admin.employee_id, compute_baselines=stub
    )
    assert seen == [_day(3)], "якорь ретро-окна — новая дата старта"
    assert report.baselines_computed is True and report.activated is True
    # строки базы уровня конкурса (race_id NULL) — фолбэк для заезда, поэтому «без базы» нет
    assert report.needs_baseline_store_ids == []
