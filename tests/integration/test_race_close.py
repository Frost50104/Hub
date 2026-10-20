"""Закрытие дня: снимки с догоном, рекорды, заморозка итогов, следующий заезд."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.org import Store
from app.models.race import RaceContest, RaceDailyStat, RaceParticipant, RaceResult, RaceSnapshot
from app.models.shadow import ShadowSite
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


async def _scheduled_contest(db, net, *, manual_stores=("A", "C"), **kw):
    """Запланированный конкурс; `manual_stores` — кому поставить ручную базу
    уровня конкурса (строка `(store, NULL)` одна на точку — тест, которому нужна
    iiko-строка на C, убирает C отсюда)."""
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
    for key in manual_stores:
        await engine.set_baseline(
            db,
            contest,
            store_id=getattr(net, key).id,
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


# ─── состав против Оргструктуры ─────────────────────────────────────────────


async def _participant(db, contest, store_id):
    return (
        await db.execute(
            select(RaceParticipant).where(
                RaceParticipant.contest_id == contest.id, RaceParticipant.store_id == store_id
            )
        )
    ).scalar_one()


async def test_reconcile_closes_archived_store_and_adds_new_linked_store(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    # точка A исключена руками — причина не переписывается
    await engine.set_participant(
        db, contest, store_id=net.A.id, included=False, actor_id=net.admin.employee_id
    )
    net.C.archived_at = datetime.now(UTC)
    site_new = uuid.uuid4()
    new_store = Store(tenant_id=tenant_id, name="Новая точка", code="Н9", site_id=site_new)
    db.add(new_store)
    db.add(
        ShadowSite(
            site_id=site_new,
            tenant_id=tenant_id,
            name="Новая точка",
            refs=[{"system": "iiko", "external_id": "dep-9"}],
            synced_at=datetime.now(UTC),
        )
    )
    await db.flush()

    report = await engine.reconcile_participants(db, contest)
    assert report.closed == [net.C.id] and report.added == [new_store.id]
    closed = await _participant(db, contest, net.C.id)
    assert closed.exclude_reason == "closed" and closed.excluded_by is None
    assert (await _participant(db, contest, net.A.id)).exclude_reason == "manual"
    added = await _participant(db, contest, new_store.id)
    assert added.excluded_at is None and added.department_id == "dep-9"
    entry = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_type == "race_participant", AuditLog.object_id == net.C.id
            )
        )
    ).scalar_one()
    assert entry.diff["reason"]["new"] == "closed" and entry.actor_id is None

    again = await engine.reconcile_participants(db, contest)
    assert not again.closed and not again.added, "идемпотентно"
    # разархивированная карточка сама не возвращается
    net.C.archived_at = None
    await db.flush()
    assert not (await engine.reconcile_participants(db, contest)).added
    assert (await _participant(db, contest, net.C.id)).exclude_reason == "closed"


async def _reasons(db, store_id):
    rows = await db.execute(
        select(AuditLog.diff)
        .where(AuditLog.object_type == "race_participant", AuditLog.object_id == store_id)
        .order_by(AuditLog.id)
    )
    return [d["reason"] for d in rows.scalars()]


async def test_reconcile_suspends_and_resumes_by_registry(db: AsyncSession, tenant_id):
    """0065: пауза в реестре выводит участника на время, снятие паузы
    возвращает его САМ; руками вернуть, пока объект на паузе, нельзя."""
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    site_c = await db.get(ShadowSite, net.C.site_id)
    site_c.suspended_at = datetime.now(UTC)
    await db.flush()

    report = await engine.reconcile_participants(db, contest)
    assert report.suspended == [net.C.id] and not report.closed and not report.resumed
    paused = await _participant(db, contest, net.C.id)
    assert paused.exclude_reason == "suspended" and paused.excluded_at is not None
    assert paused.excluded_by is None
    again = await engine.reconcile_participants(db, contest)
    assert not again.suspended and not again.resumed, "идемпотентно"
    with pytest.raises(engine.RaceConflictError):
        await engine.set_participant(
            db, contest, store_id=net.C.id, included=True, actor_id=net.admin.employee_id
        )

    site_c.suspended_at = None
    await db.flush()
    report = await engine.reconcile_participants(db, contest)
    assert report.resumed == [net.C.id] and not report.suspended
    back = await _participant(db, contest, net.C.id)
    assert back.excluded_at is None and back.exclude_reason is None
    await db.refresh(net.C)
    assert net.C.archived_at is None, "карточку пауза не трогает"
    assert await _reasons(db, net.C.id) == [
        {"old": None, "new": "suspended"},
        {"old": "suspended", "new": None},
    ]
    assert not (await engine.reconcile_participants(db, contest)).resumed


async def test_suspended_at_creation_resumes_one_of_twins_and_closed_stays_closed(
    db: AsyncSession, tenant_id
):
    """Объект на паузе в момент создания конкурса: участники рождаются
    `suspended` и подразделение не держат. Снятие паузы: из пары дублей одного
    объекта возвращается первая, вторая — `duplicate`; карточку, закрытую за
    время паузы, сверка закрывает навсегда."""
    net = await seed_network(db, tenant_id)
    site_a = await db.get(ShadowSite, net.A.site_id)
    site_a.suspended_at = datetime.now(UTC)
    await db.flush()
    contest = await _scheduled_contest(db, net)
    for store in (net.A, net.B):
        assert (await _participant(db, contest, store.id)).exclude_reason == "suspended"
    assert (await _participant(db, contest, net.C.id)).excluded_at is None
    site_c = await db.get(ShadowSite, net.C.site_id)
    site_c.suspended_at = datetime.now(UTC)
    await db.flush()
    assert (await engine.reconcile_participants(db, contest)).suspended == [net.C.id]

    net.C.archived_at = datetime.now(UTC)
    site_a.suspended_at = site_c.suspended_at = None
    await db.flush()
    report = await engine.reconcile_participants(db, contest)
    assert report.resumed == [net.A.id] and report.closed == [net.C.id]
    assert (await _participant(db, contest, net.A.id)).excluded_at is None
    assert (await _participant(db, contest, net.B.id)).exclude_reason == "duplicate"
    closed = await _participant(db, contest, net.C.id)
    assert closed.exclude_reason == "closed" and closed.excluded_at is not None
    assert await _reasons(db, net.B.id) == [{"old": "suspended", "new": "duplicate"}]
    assert await _reasons(db, net.C.id) == [
        {"old": None, "new": "suspended"},
        {"old": "suspended", "new": "closed"},
    ]


async def test_late_joiner_gets_joined_race_seq_in_standings_and_admin(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net)
    races = await read.load_races(db, contest)
    await engine.close_day(db, contest, close_day=_day(6))  # заезд 1 завершён
    site_new = uuid.uuid4()
    late = Store(tenant_id=tenant_id, name="Поздняя", code="П9", site_id=site_new)
    db.add(late)
    db.add(
        ShadowSite(
            site_id=site_new,
            tenant_id=tenant_id,
            name="Поздняя",
            refs=[{"system": "iiko", "external_id": "dep-late"}],
            synced_at=datetime.now(UTC),
        )
    )
    await db.flush()
    await engine.reconcile_participants(db, contest)
    row = await _participant(db, contest, late.id)
    # вошла в день 9 — второй заезд
    row.created_at = datetime(2026, 6, 10, 9, tzinfo=UTC)
    await db.flush()
    participants = await read.load_participants(db, contest)
    standings = await read.standings_payload(db, contest, races, participants)
    by_id = {s["store_id"]: s for s in standings}
    assert by_id[late.id]["joined_race_seq"] == 2 and by_id[late.id]["missed_races"] == 1
    assert by_id[net.A.id]["joined_race_seq"] is None


# ─── финализация предварительных баз ────────────────────────────────────────


async def _iiko_row(db, contest, store_id, *, race_id, period_to, set_at):
    """iiko-строка с заданным моментом расчёта: `upsert_baseline` ставит now()."""
    row = await upsert_baseline(
        db,
        contest=contest,
        store_id=store_id,
        race_id=race_id,
        value=2.2,
        source="iiko",
        period_from=period_to - timedelta(days=27),
        period_to=period_to,
    )
    row.set_at = set_at
    await db.flush()
    return row


async def test_preliminary_scopes_only_iiko_rows_computed_before_window_closed(
    db: AsyncSession, tenant_id
):
    from zoneinfo import ZoneInfo

    from app.services.race.baselines import preliminary_scopes

    tz = ZoneInfo("Europe/Moscow")
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, manual_stores=("A",))  # A — ручная база
    early = datetime(2026, 5, 29, 12, 0, tzinfo=tz)  # окно по 31.05, посчитано 29.05
    await _iiko_row(db, contest, net.C.id, race_id=None, period_to=_day(-1), set_at=early)
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == [None]
    # окно ещё не закрылось по through_day — не трогаем
    assert await preliminary_scopes(db, contest.id, through_day=_day(-2), tz=tz) == []
    # посчитано после полуночи 01.06 — окончательная
    late = datetime(2026, 6, 1, 3, 45, tzinfo=tz)
    await _iiko_row(db, contest, net.C.id, race_id=None, period_to=_day(-1), set_at=late)
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == []


async def test_preliminary_scopes_ignore_excluded_store_until_reincluded(
    db: AsyncSession, tenant_id
):
    """Инцидент 05–17.10: «Витебский 101» исключили через 25 минут после расчёта
    базы, `compute_baselines` исключённых не переписывает — и её строка держала
    scope предварительным 21 финализацию в сутки. Строка исключённой точки не
    считается; возврат точки в состав снова вводит её в правило."""
    from zoneinfo import ZoneInfo

    from app.services.race.baselines import preliminary_scopes

    tz = ZoneInfo("Europe/Moscow")
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, manual_stores=("A",))
    early = datetime(2026, 5, 29, 12, 0, tzinfo=tz)
    await _iiko_row(db, contest, net.C.id, race_id=None, period_to=_day(-1), set_at=early)
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == [None]

    await engine.set_participant(
        db, contest, store_id=net.C.id, included=False, actor_id=net.admin.employee_id
    )
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == []
    await engine.set_participant(
        db, contest, store_id=net.C.id, included=True, actor_id=net.admin.employee_id
    )
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == [None]

    # дубль B исключён сидом (делит подразделение с A): его строка не считается,
    # пока B не вернут в состав — тогда A вытесняется, а строка B снова в правиле
    await _iiko_row(
        db,
        contest,
        net.C.id,
        race_id=None,
        period_to=_day(-1),
        set_at=datetime(2026, 6, 1, 3, 45, tzinfo=tz),
    )
    await _iiko_row(db, contest, net.B.id, race_id=None, period_to=_day(-1), set_at=early)
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == []
    replaced = await engine.set_participant(
        db, contest, store_id=net.B.id, included=True, actor_id=net.admin.employee_id
    )
    assert replaced == net.A.id
    assert await preliminary_scopes(db, contest.id, through_day=_day(-1), tz=tz) == [None]


async def test_finalize_recomputes_contest_baseline_once_and_keeps_manual(
    db: AsyncSession, tenant_id, monkeypatch
):
    from zoneinfo import ZoneInfo

    from app.services.race import finalize, iiko_pull
    from app.services.race.baselines import load_baselines

    tz = ZoneInfo("Europe/Moscow")
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, manual_stores=("A",))
    early = datetime(2026, 5, 29, 12, 0, tzinfo=tz)
    await _iiko_row(db, contest, net.C.id, race_id=None, period_to=_day(-1), set_at=early)
    await db.commit()
    calls: list[tuple[str, object]] = []

    async def stub(session, *, contest, race, force=False, pull=True, set_by=None):  # noqa: ARG001
        calls.append((contest.title, None if race is None else race.id))
        # «пересчёт» — та же строка с set_at = now(), как делает настоящий compute_baselines
        await upsert_baseline(
            session,
            contest=contest,
            store_id=net.C.id,
            race_id=None,
            value=2.4,
            source="iiko",
            period_from=_day(-28),
            period_to=_day(-1),
        )
        return iiko_pull.BaselineReport(
            period_from=_day(-28),
            period_to=_day(-1),
            computed=1,
            skipped_manual=1,
            empty=0,
            pulled=True,
        )

    monkeypatch.setattr(iiko_pull, "compute_baselines", stub)
    report = await finalize.finalize_baselines(db, tenant_id=tenant_id, through_day=_day(-1))
    assert calls == [("Тест", None)]
    assert report.finalized == [(contest.id, None)] and report.failed == []
    rows = await load_baselines(db, contest, None)
    assert rows[net.A.id].source == "manual" and rows[net.A.id].value == 2.0
    assert rows[net.C.id].value == 2.4
    # повторный прогон — set_at уже после полуночи 01.06, пересчитывать нечего
    report2 = await finalize.finalize_baselines(db, tenant_id=tenant_id, through_day=_day(-1))
    assert calls == [("Тест", None)] and report2.finalized == []


async def test_finalize_race_mode_touches_only_races_whose_window_closed(
    db: AsyncSession, tenant_id, monkeypatch
):
    from zoneinfo import ZoneInfo

    from app.services.race import finalize, iiko_pull

    tz = ZoneInfo("Europe/Moscow")
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, baseline_mode="race")
    races = sorted((await read.load_races(db, contest)), key=lambda r: r.seq)
    early = datetime(2026, 5, 29, 12, 0, tzinfo=tz)
    # заезд №1: окно по 31.05, посчитано при schedule — предварительная
    await _iiko_row(db, contest, net.C.id, race_id=races[0].id, period_to=_day(-1), set_at=early)
    # заезд №2: окно по 07.06, строка «заранее» — окно ещё не закрылось
    await _iiko_row(db, contest, net.C.id, race_id=races[1].id, period_to=_day(6), set_at=early)
    await db.commit()
    seen: list = []

    async def stub(session, *, contest, race, force=False, pull=True, set_by=None):  # noqa: ARG001
        seen.append(None if race is None else race.seq)
        return iiko_pull.BaselineReport(
            period_from=_day(-28),
            period_to=_day(-1),
            computed=0,
            skipped_manual=0,
            empty=0,
            pulled=True,
        )

    monkeypatch.setattr(iiko_pull, "compute_baselines", stub)
    await finalize.finalize_baselines(db, tenant_id=tenant_id, through_day=_day(-1))
    assert seen == [1]


async def test_finalize_iiko_failure_rolls_back_and_reports(
    db: AsyncSession, tenant_id, monkeypatch
):
    from zoneinfo import ZoneInfo

    from app.services.iiko import service as iiko_service
    from app.services.race import finalize, iiko_pull
    from app.services.race.baselines import load_baselines

    tz = ZoneInfo("Europe/Moscow")
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, manual_stores=("A",))
    early = datetime(2026, 5, 29, 12, 0, tzinfo=tz)
    await _iiko_row(db, contest, net.C.id, race_id=None, period_to=_day(-1), set_at=early)
    await db.commit()

    async def boom(session, *, contest, race, force=False, pull=True, set_by=None):  # noqa: ARG001
        raise iiko_service.IikoBusy("слот занят")

    monkeypatch.setattr(iiko_pull, "compute_baselines", boom)
    contest_id, c_id = contest.id, net.C.id  # rollback внутри finalize протухает ORM-объекты
    report = await finalize.finalize_baselines(db, tenant_id=tenant_id, through_day=_day(-1))
    assert report.failed == [(contest_id, None)] and report.finalized == []
    contest = await db.get(RaceContest, contest_id)
    rows = await load_baselines(db, contest, None)
    assert rows[c_id].value == 2.2, "база осталась предварительной целиком, не половинчатой"


# ─── закрытие без полной выгрузки и окно дотяжки (17.10) ────────────────────


async def test_close_day_without_complete_sales_defers_snapshots_and_finish(
    db: AsyncSession, tenant_id
):
    """Инцидент 14–17.10: выгрузка iiko упала, а закрытие писало снимки по
    устаревшим данным и заморозило бы итоги. Теперь день откладывается, первое
    закрытие с полной выгрузкой дописывает всё и завершает заезд."""
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=1)
    race = (await read.load_races(db, contest))[0]
    for n in range(0, 7):
        await _stat(db, tenant_id, "dep-1", _day(n), 100, 300 if n == 1 else 220)
        await _stat(db, tenant_id, "dep-2", _day(n), 100, 200)

    r = await engine.close_day(db, contest, close_day=_day(6), sales_complete=False)
    assert r.snapshots == 0 and r.deferred and r.deferred_days == 7
    assert not r.finished_race_ids and not r.contest_finished
    await db.refresh(race)
    assert race.status == "active" and contest.status == "active"
    assert await _snaps(db, race.id, net.A.id) == []
    assert (await db.execute(select(RaceResult).where(RaceResult.race_id == race.id))).all() == []

    r2 = await engine.close_day(db, contest, close_day=_day(6))
    assert r2.snapshots == 14 and not r2.deferred
    assert r2.finished_race_ids == [race.id] and r2.contest_finished
    a = await _snaps(db, race.id, net.A.id)
    assert len(a) == 7 and a[1].is_record and not a[0].is_record


async def test_close_day_deferred_still_activates_and_requests_baseline(
    db: AsyncSession, tenant_id
):
    from zoneinfo import ZoneInfo

    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=2, baseline_mode="race")
    races = await read.load_races(db, contest)
    # у идущего заезда база из iiko есть (посчитана при планировании)
    await _iiko_row(
        db,
        contest,
        net.A.id,
        race_id=races[0].id,
        period_to=_day(-1),
        set_at=datetime(2026, 6, 1, 3, 45, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    r = await engine.close_day(db, contest, close_day=_day(6), sales_complete=False)
    assert r.deferred and r.snapshots == 0 and not r.finished_race_ids
    assert r.races_needing_baseline == [races[1].id], "список по датам, от выгрузки не зависит"
    await db.refresh(races[1])
    assert races[1].status == "scheduled", "следующий заезд ждёт завершения предыдущего"

    r2 = await engine.close_day(db, contest, close_day=_day(7))
    assert r2.finished_race_ids == [races[0].id] and r2.activated_race_ids == [races[1].id]
    assert len(await _snaps(db, races[0].id, net.A.id)) == 7
    r3 = await engine.close_day(db, contest, close_day=_day(8))
    assert r3.snapshots == 4, "заезд 2: D7 и D8 по двум точкам"


async def test_pull_window_follows_last_snapshot(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=1)
    # снимков нет, заезд стартует D0 — штатное «вчера + сегодня»
    assert await engine.pull_window(db, contest, through=_day(0)) == (_day(-1), _day(0))
    for n in range(0, 3):
        await _stat(db, tenant_id, "dep-1", _day(n), 100, 220)
    await engine.close_day(db, contest, close_day=_day(2))
    # норма: закрытие D3 и дневной тик D3 — [D2, D3]
    assert await engine.pull_window(db, contest, through=_day(3)) == (_day(2), _day(3))
    # две ночи без выгрузки (снимков за D3, D4 нет): тик D5 догоняет от D3
    assert await engine.pull_window(db, contest, through=_day(5)) == (_day(3), _day(5))


# ─── ремонт снимков ──────────────────────────────────────────────────────────


async def test_rebuild_snapshots_rewrites_tail_and_recomputes_records(db: AsyncSession, tenant_id):
    """Три одинаковых снимка после отказа iiko → дотяжка данных → ремонт хвоста
    тем же кодом, что ночное закрытие."""
    net = await seed_network(db, tenant_id)
    contest = await _scheduled_contest(db, net, weeks_total=1)
    race = (await read.load_races(db, contest))[0]
    await _stat(db, tenant_id, "dep-1", _day(0), 100, 220)  # 110
    for n in range(0, 3):
        await _stat(db, tenant_id, "dep-2", _day(n), 100, 200)  # 100
    await engine.close_day(db, contest, close_day=_day(0))
    # «до 17.10»: ночи D1 и D2 закрылись, хотя данных dep-1 за D1–D2 не было
    await engine.close_day(db, contest, close_day=_day(2))
    a = await _snaps(db, race.id, net.A.id)
    assert [(int(s.cells), s.is_record) for s in a] == [(110, False)] * 3
    d0_id = a[0].id

    await _stat(db, tenant_id, "dep-1", _day(1), 100, 300)  # cum 2,6 → 130
    await _stat(db, tenant_id, "dep-1", _day(2), 100, 150)  # cum 2,233 → 112
    report = await engine.rebuild_snapshots(
        db, contest, race, day_from=_day(1), day_to=_day(2), today=_day(3)
    )
    assert (report.deleted, report.written, report.kept_excluded) == (4, 4, 0)
    assert (report.records_before, report.records_after) == (0, 1)
    a = await _snaps(db, race.id, net.A.id)
    assert [(s.day, int(s.cells), s.is_record) for s in a] == [
        (_day(0), 110, False),
        (_day(1), 130, True),
        (_day(2), 112, False),
    ]
    assert a[0].id == d0_id, "строки до окна не тронуты"
    assert a[1].record_notified_at is None, "рекорд уйдёт обычным тиком"

    again = await engine.rebuild_snapshots(
        db, contest, race, day_from=_day(1), day_to=_day(2), today=_day(3)
    )
    assert again.written == 4
    assert [int(s.cells) for s in await _snaps(db, race.id, net.A.id)] == [110, 130, 112]

    with pytest.raises(engine.RaceConflictError):  # окно не упирается в последний снимок
        await engine.rebuild_snapshots(
            db, contest, race, day_from=_day(1), day_to=_day(1), today=_day(3)
        )
    with pytest.raises(engine.RaceValidationError):  # раньше старта заезда
        await engine.rebuild_snapshots(
            db, contest, race, day_from=_day(-1), day_to=_day(2), today=_day(3)
        )
    with pytest.raises(engine.RaceValidationError):  # сегодняшний день ещё не закрыт
        await engine.rebuild_snapshots(
            db, contest, race, day_from=_day(2), day_to=_day(2), today=_day(2)
        )

    # исключённая точка: её строки в окне остаются, переписываются только живые
    await engine.set_participant(
        db, contest, store_id=net.C.id, included=False, actor_id=net.admin.employee_id
    )
    rep = await engine.rebuild_snapshots(
        db, contest, race, day_from=_day(1), day_to=_day(2), today=_day(3)
    )
    assert (rep.deleted, rep.written, rep.kept_excluded) == (2, 2, 2)
    assert len(await _snaps(db, race.id, net.C.id)) == 3

    # завершённый заезд — итоги заморожены, снимки не переписываются
    for n in range(3, 7):
        await _stat(db, tenant_id, "dep-1", _day(n), 100, 300)
    await engine.close_day(db, contest, close_day=_day(6))
    await db.refresh(race)
    with pytest.raises(engine.RaceConflictError):
        await engine.rebuild_snapshots(
            db, contest, race, day_from=_day(5), day_to=_day(6), today=_day(7)
        )
