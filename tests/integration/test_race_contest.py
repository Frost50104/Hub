"""Конкурс: участники из реестра, дубли подразделений, лиги, расписание, состав."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Store, StoreGroupMember
from app.services.race import engine, read
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


# Роль testcontainers — суперюзер и RLS не режет: `materialize_participants`
# читает `stores` без ручного tenant-фильтра (в проде скоупит RLS) и под
# суперюзером видел бы магазины соседних тестов. Поэтому — реальная app-роль.
@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield

D0 = date(2026, 6, 1)


async def _contest(db, net, **kw):
    return await engine.create_contest(
        db,
        tenant_id=net.A.tenant_id,
        actor_id=net.admin.employee_id,
        title=kw.pop("title", "Осень"),
        starts_on=kw.pop("starts_on", D0),
        league_group_ids=kw.pop("league_group_ids", [net.g1.id, net.g2.id]),
        **kw,
    )


async def test_create_materializes_participants_dedupes_department_and_snapshots_leagues(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    parts = {
        p.store_id: p for p in await read.load_participants(db, contest, include_excluded=True)
    }
    assert parts[net.A.id].excluded_at is None
    assert parts[net.B.id].exclude_reason == "duplicate", "второй магазин того же подразделения"
    assert parts[net.C.id].excluded_at is None
    assert net.D.id not in parts, "точка без реестра — не участник"
    leagues = {lg.name: lg.id for lg in await read.load_leagues(db, contest)}
    assert set(leagues) == {"Центр", "Область"}
    assert parts[net.A.id].league_id == leagues["Центр"]
    assert parts[net.C.id].league_id == leagues["Область"]


async def test_store_in_two_leagues_is_rejected_by_name(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    db.add(StoreGroupMember(tenant_id=tenant_id, group_id=net.g2.id, store_id=net.A.id))
    await db.flush()
    with pytest.raises(engine.RaceValidationError) as e:
        await _contest(db, net)
    assert "Арсенальная" in str(e.value) and "Центр" in str(e.value)


async def test_archived_store_membership_does_not_trigger_overlap(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    ghost = Store(tenant_id=tenant_id, name="Закрытая", site_id=None)
    from datetime import UTC, datetime

    ghost.archived_at = datetime.now(UTC)
    db.add(ghost)
    await db.flush()
    db.add_all(
        [
            StoreGroupMember(tenant_id=tenant_id, group_id=net.g1.id, store_id=ghost.id),
            StoreGroupMember(tenant_id=tenant_id, group_id=net.g2.id, store_id=ghost.id),
        ]
    )
    await db.flush()
    contest = await _contest(db, net)  # не падает
    assert contest.status == "draft"


async def test_schedule_generates_races_and_activates_when_start_is_today(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    report = await engine.schedule(
        db, contest, today=D0, actor_id=net.admin.employee_id, compute_baselines=None
    )
    races = await read.load_races(db, contest)
    assert report.races == 4 and [r.seq for r in races] == [1, 2, 3, 4]
    assert races[0].starts_on == D0 and races[-1].ends_on == contest.ends_on
    assert contest.status == "active" and races[0].status == "active"
    assert races[1].status == "scheduled"
    assert set(report.needs_baseline_store_ids) == {net.A.id, net.C.id}, "без iiko базы нет"

    second = await _contest(db, net, title="Второй", starts_on=D0)
    with pytest.raises(engine.RaceConflictError):
        await engine.schedule(
            db, second, today=D0, actor_id=net.admin.employee_id, compute_baselines=None
        )


async def test_schedule_rejects_past_start(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    with pytest.raises(engine.RaceValidationError):
        await engine.schedule(
            db,
            contest,
            today=date(2026, 6, 2),
            actor_id=net.admin.employee_id,
            compute_baselines=None,
        )


async def test_update_shape_only_in_draft(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    await engine.update_contest(
        db, contest, actor_id=net.admin.employee_id, race_length_days=14, weeks_total=4
    )
    assert contest.race_length_days == 14
    await engine.schedule(
        db, contest, today=D0, actor_id=net.admin.employee_id, compute_baselines=None
    )
    assert len(await read.load_races(db, contest)) == 2
    with pytest.raises(engine.RaceConflictError):
        await engine.update_contest(db, contest, actor_id=net.admin.employee_id, starts_on=D0)
    await engine.update_contest(db, contest, actor_id=net.admin.employee_id, title="Новое имя")
    assert contest.title == "Новое имя"


async def test_including_twin_swaps_department_holder(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    replaced = await engine.set_participant(
        db, contest, store_id=net.B.id, included=True, actor_id=net.admin.employee_id
    )
    assert replaced == net.A.id
    parts = {
        p.store_id: p for p in await read.load_participants(db, contest, include_excluded=True)
    }
    assert parts[net.B.id].excluded_at is None and parts[net.A.id].exclude_reason == "duplicate"


async def test_store_with_race_rows_cannot_be_deleted(db: AsyncSession, tenant_id):
    from app.api.org import delete_store

    net = await seed_network(db, tenant_id)
    await _contest(db, net)
    with pytest.raises(HTTPException) as e:
        await delete_store(net.A.id, net.admin, db)
    assert e.value.status_code == 409
