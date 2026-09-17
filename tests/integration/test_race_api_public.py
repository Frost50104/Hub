"""Гейты выключателя, трек с «моей точкой», публичная ТВ-ручка без ПДн, пуши."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import race as race_api
from app.api.public import get_public_race
from app.config import get_settings
from app.models.notification import Notification
from app.models.race import RaceDailyStat, RaceSnapshot
from app.schemas.race import RaceSettingsPut
from app.services.notify_batch import drain
from app.services.race import engine, gate, read, tv_token
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


# Роль testcontainers — суперюзер и RLS не режет: `materialize_participants`
# читает `stores` без ручного tenant-фильтра (в проде скоупит RLS) и под
# суперюзером видел бы магазины соседних тестов. Поэтому — реальная app-роль.
@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


async def _active_contest_today(db, net):
    today = engine.today_local()
    contest = await engine.create_contest(
        db,
        tenant_id=net.A.tenant_id,
        actor_id=net.admin.employee_id,
        title="Сегодня",
        starts_on=today,
        league_group_ids=[net.g1.id, net.g2.id],
    )
    await engine.schedule(
        db, contest, today=today, actor_id=net.admin.employee_id, compute_baselines=None
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
    db.add_all(
        [
            RaceDailyStat(
                tenant_id=net.A.tenant_id,
                department_id="dep-1",
                day=today,
                receipts=100,
                items=260,
                pulled_at=datetime.now(UTC),
            ),
            RaceDailyStat(
                tenant_id=net.A.tenant_id,
                department_id="dep-2",
                day=today,
                receipts=100,
                items=200,
                pulled_at=datetime.now(UTC),
            ),
        ]
    )
    await db.flush()
    return contest, today


async def test_module_off_means_404_for_users_and_409_for_admin(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id, enable=False)
    with pytest.raises(HTTPException) as e:
        await race_api.get_track(net.emp_a, db)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await race_api.list_contests(net.admin, db)
    assert e.value.status_code == 409
    settings = await race_api.get_settings_endpoint(net.admin, db)
    assert settings.enabled is False and settings.env_enabled is True
    await race_api.put_settings(RaceSettingsPut(enabled=True), net.admin, db)
    track = await race_api.get_track(net.emp_a, db)
    assert track.contest is None and track.my_store_id == net.A.id


async def test_env_flag_hides_even_settings(db: AsyncSession, tenant_id, monkeypatch):
    net = await seed_network(db, tenant_id)
    monkeypatch.setenv("SIGNARIS_HUB_RACE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as e:
            await race_api.get_settings_endpoint(net.admin, db)
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            await race_api.get_track(net.admin, db)
        assert e.value.status_code == 404
    finally:
        monkeypatch.delenv("SIGNARIS_HUB_RACE_ENABLED")
        get_settings.cache_clear()


async def test_track_ranks_live_positions_and_marks_my_store(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest, _today = await _active_contest_today(db, net)
    track = await race_api.get_track(net.emp_a, db)
    assert track.contest is not None and track.race is not None and track.race.status == "active"
    assert track.my_store_id == net.A.id
    rows = {p.store_id: p for p in track.participants}
    assert rows[net.A.id].cells == 130 and rows[net.A.id].place == 1
    assert rows[net.C.id].cells == 100 and rows[net.C.id].place == 2
    assert rows[net.A.id].pct == 30.0 and rows[net.A.id].dynamics is None, "снимков ещё нет"
    assert net.B.id not in rows, "исключённый дубль на треке не показывается"
    office = await race_api.get_track(net.office, db)
    assert office.my_store_id is None, "офис без точки не падает в 500"


async def test_public_tv_link_serves_track_without_pii_and_respects_gate(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    await _active_contest_today(db, net)
    link = await tv_token.create_tv_token(db, tenant_id=tenant_id, actor_id=net.admin.employee_id)
    await db.commit()  # публичная ручка открывает свои сессии

    payload = await get_public_race(str(link.token), Response())
    assert payload.contest is not None and len(payload.participants) == 2
    dumped = payload.model_dump()

    def _keys(obj, acc):
        if isinstance(obj, dict):
            for k, v in obj.items():
                acc.add(k)
                _keys(v, acc)
        elif isinstance(obj, list):
            for v in obj:
                _keys(v, acc)
        return acc

    keys = _keys(dumped, set())
    assert not keys & {"email", "employee_id", "full_name", "tenant_id", "my_store_id"}

    with pytest.raises(HTTPException) as e:
        await get_public_race("not-a-uuid", Response())
    assert e.value.status_code == 404

    await gate.set_tenant_enabled(db, tenant_id, False)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await get_public_race(str(link.token), Response())
    assert e.value.status_code == 404
    await gate.set_tenant_enabled(db, tenant_id, True)
    await db.commit()

    assert await tv_token.revoke_tv_token(
        db, tenant_id=tenant_id, token=link.token, actor_id=net.admin.employee_id
    )
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await get_public_race(str(link.token), Response())
    assert e.value.status_code == 404


async def test_notifications_go_once_after_nine_to_people_of_included_stores(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest, today = await _active_contest_today(db, net)
    race = (await read.load_races(db, contest))[0]
    db.add(
        RaceSnapshot(
            tenant_id=tenant_id,
            race_id=race.id,
            store_id=net.A.id,
            day=today - timedelta(days=1),
            receipts_cum=100,
            items_cum=260,
            avg=2.6,
            base=2.0,
            pct=30.0,
            cells=130,
            is_record=True,
        )
    )
    await db.commit()

    early = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=5)  # 08:00 MSK
    assert await engine.send_pending_notifications(tenant_id, now=early) == 0

    later = early.replace(hour=7)  # 10:00 MSK
    sent = await engine.send_pending_notifications(tenant_id, now=later)
    assert sent > 0
    rows = (
        await db.execute(
            select(Notification.employee_id, Notification.kind).where(
                Notification.tenant_id == tenant_id
            )
        )
    ).all()
    who = {
        getattr(v, "employee_id", None): k
        for k, v in vars(net).items()
        if hasattr(v, "employee_id")
    }
    started = {who.get(emp, str(emp)) for emp, kind in rows if kind == "race.started"}
    record = {who.get(emp, str(emp)) for emp, kind in rows if kind == "race.record"}
    assert started == {"emp_a", "emp_c"}, (
        "дубль B и касса A пушей не получают, офис без точки — тоже"
    )
    assert record == {"emp_a"}
    assert await engine.send_pending_notifications(tenant_id, now=later) == 0, "дедуп"
    await drain(timeout_sec=5)
