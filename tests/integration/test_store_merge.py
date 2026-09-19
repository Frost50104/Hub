"""Слияние карточек одного объекта реестра: каждое место данных переезжает,
проигравший — в архив, повтор — 409. Сид `seed_network`: A и B — дубли
объекта `site_a` (B — исключённый дубль в гонке), C — другой объект."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.org import merge_store, merge_store_preview, update_store
from app.models.audience import Audience, AudienceRule
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Position, StoreGroupMember
from app.models.race import RaceParticipant
from app.models.shift import ShiftPosting
from app.schemas.org import MergeBody, StoreUpdate
from app.services.race import engine
from app.services.store_merge import MergeError, apply_merge, plan_merge
from tests.integration._race_seed import seed_network

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _rls(rls_enforced):  # noqa: ARG001 — фикстура нужна побочным эффектом
    yield


async def _profile(db, employee_id) -> EmployeeProfile:
    return (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.employee_id == employee_id))
    ).scalar_one()


async def _contest(db, net):
    return await engine.create_contest(
        db,
        tenant_id=net.A.tenant_id,
        actor_id=net.admin.employee_id,
        title="Осень",
        starts_on=datetime.now(UTC).date(),
        league_group_ids=[],
    )


async def test_merge_moves_every_reference_and_archives_loser(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    # у B: членство в группе, где A уже есть (g1) → удалится; в g2 — переедет;
    # ТУ-закрепление, смена, правило аудитории, ответ опроса нет (нет опроса).
    db.add(StoreGroupMember(tenant_id=tenant_id, group_id=net.g1.id, store_id=net.B.id))
    tu = await _profile(db, net.office.employee_id)
    db.add(TuStoreAssignment(profile_id=tu.id, store_id=net.B.id, tenant_id=tenant_id))
    db.add(TuStoreAssignment(profile_id=tu.id, store_id=net.A.id, tenant_id=tenant_id))
    position = Position(tenant_id=tenant_id, name="Бариста")
    db.add(position)
    await db.flush()
    db.add(
        ShiftPosting(
            tenant_id=tenant_id,
            store_id=net.B.id,
            position_id=position.id,
            starts_at=datetime.now(UTC),
            ends_at=datetime.now(UTC) + timedelta(hours=8),
            created_by=net.admin.employee_id,
        )
    )
    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            store_ids=[net.B.id, net.A.id],
        )
    )
    await db.flush()

    plan = await plan_merge(db, loser_id=net.B.id, winner_id=net.A.id)
    c = plan.counts
    assert (c.profiles, c.group_members, c.group_members_dropped, c.tu, c.tu_dropped) == (
        1,
        1,
        1,
        0,
        1,
    )
    assert (c.shifts, c.rules, c.race_participants_dropped, c.race_participants_moved) == (
        1,
        1,
        1,
        0,
    )
    assert plan.recommended_winner_id == net.A.id, "у A больше людей"

    await apply_merge(db, plan, actor_id=net.admin.employee_id)
    await db.refresh(net.B)
    assert net.B.archived_at is not None and net.B.site_id == net.A.site_id, "site_id остаётся"
    assert (await _profile(db, net.emp_b.employee_id)).store_id == net.A.id
    groups = {
        r[0]
        for r in await db.execute(
            select(StoreGroupMember.group_id).where(StoreGroupMember.store_id == net.A.id)
        )
    }
    assert groups == {net.g1.id, net.g2.id}
    assert not (
        await db.execute(select(StoreGroupMember).where(StoreGroupMember.store_id == net.B.id))
    ).all()
    assert not (
        await db.execute(select(TuStoreAssignment).where(TuStoreAssignment.store_id == net.B.id))
    ).all()
    assert (
        await db.execute(select(ShiftPosting.store_id).where(ShiftPosting.store_id == net.A.id))
    ).all()
    rule = (
        await db.execute(select(AudienceRule).where(AudienceRule.audience_id == audience.id))
    ).scalar_one()
    assert rule.store_ids == [net.A.id], "дедуп массива"
    rows = (
        (await db.execute(select(RaceParticipant).where(RaceParticipant.contest_id == contest.id)))
        .scalars()
        .all()
    )
    assert {r.store_id for r in rows} == {net.A.id, net.C.id}, "исключённый дубль удалён"

    with pytest.raises(MergeError):
        await plan_merge(db, loser_id=net.B.id, winner_id=net.A.id)


async def test_merge_keeps_active_race_participant_when_loser_was_the_active_one(
    db: AsyncSession, tenant_id
):
    net = await seed_network(db, tenant_id)
    contest = await _contest(db, net)
    # делаем B активным участником, A — исключённым
    await engine.set_participant(
        db, contest, store_id=net.B.id, included=True, actor_id=net.admin.employee_id
    )
    plan = await plan_merge(db, loser_id=net.B.id, winner_id=net.A.id)
    assert plan.counts.race_participants_moved == 1
    await apply_merge(db, plan, actor_id=net.admin.employee_id)
    rows = {
        r.store_id: r
        for r in (
            await db.execute(
                select(RaceParticipant).where(RaceParticipant.contest_id == contest.id)
            )
        ).scalars()
    }
    assert net.B.id not in rows and rows[net.A.id].excluded_at is None


async def test_merge_guards(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    with pytest.raises(MergeError, match="одного объекта"):
        await plan_merge(db, loser_id=net.C.id, winner_id=net.A.id)
    with pytest.raises(MergeError, match="одна и та же"):
        await plan_merge(db, loser_id=net.A.id, winner_id=net.A.id)
    with pytest.raises(MergeError, match="не найдена"):
        await plan_merge(db, loser_id=uuid.uuid4(), winner_id=net.A.id)


async def test_merge_handlers_and_rename_conflict_is_409(db: AsyncSession, tenant_id):
    net = await seed_network(db, tenant_id)
    await _contest(db, net)
    preview = await merge_store_preview(net.B.id, net.A.id, net.admin, db)
    assert preview.recommended_winner_id == net.A.id and preview.counts["profiles"] == 1
    out = await merge_store(net.B.id, MergeBody(into=net.A.id), net.admin, db)
    assert out.loser_id == net.B.id and out.counts["profiles"] == 1
    with pytest.raises(HTTPException) as e:
        await merge_store(net.B.id, MergeBody(into=net.A.id), net.admin, db)
    assert e.value.status_code == 409
    # переименование в занятое имя — 409, не 500
    with pytest.raises(HTTPException) as e:
        await update_store(net.C.id, StoreUpdate(name=net.A.name), net.admin, db)
    assert e.value.status_code == 409 and "уже существует" in e.value.detail
