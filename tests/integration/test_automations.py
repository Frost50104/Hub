"""Integration-тесты Ф5: автосценарии (ретро-защита, идемпотентность,
cancel при архиве), правило неактивности, learn-поиск, аналитика."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.automations_run import _execute_pending, _materialize
from app.jobs.inactivity import _process_tenant
from app.models.automation import AutomationJob, AutomationRule
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position
from app.models.progress import CourseAssignment
from app.services.employee_profiles import archive_profile
from tests.integration.test_courses import _mk_course, _mk_member

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.services import notify_batch

    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def test_automation_assigns_course_once(db: AsyncSession, tenant_id: uuid.UUID):
    _member, profile = await _mk_member(db, tenant_id, email="auto1@t.ru")
    course, _lessons = await _mk_course(db, tenant_id, lesson_count=1, title="Welcome")
    rule = AutomationRule(
        tenant_id=tenant_id,
        title="Welcome новичкам",
        trigger="profile_activated",
        course_id=course.id,
        due_days=14,
        applies_from=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(rule)
    await db.flush()

    # Ассерты по СВОЕМУ профилю: superuser в testcontainers видит
    # закоммиченные профили других тестов, точные счётчики нестабильны.
    created = await _materialize(db, rule)
    assert created >= 1
    executed = await _execute_pending(db, tenant_id)
    assert executed >= 1
    await db.flush()

    assignment = (
        await db.execute(
            select(CourseAssignment).where(
                CourseAssignment.course_id == course.id,
                CourseAssignment.profile_id == profile.id,
            )
        )
    ).scalar_one()
    assert assignment.source == "automation"
    assert assignment.due_at is not None

    # Повторный прогон — job НАШЕГО профиля не дублируется.
    await _materialize(db, rule)
    my_jobs = (
        (
            await db.execute(
                select(AutomationJob).where(
                    AutomationJob.rule_id == rule.id,
                    AutomationJob.profile_id == profile.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(my_jobs) == 1


async def test_automation_no_retro_and_position_filter(
    db: AsyncSession, tenant_id: uuid.UUID
):
    _old_member, old_profile = await _mk_member(db, tenant_id, email="veteran2@t.ru")
    pos = Position(tenant_id=tenant_id, name="Бариста")
    db.add(pos)
    await db.flush()
    # Ветеран заведён «10 дней назад» (в одной транзакции PG now() одинаков —
    # выставляем created_at явно, иначе ретро-случай не смоделировать).
    old_profile.created_at = datetime.now(UTC) - timedelta(days=10)

    course, _ = await _mk_course(db, tenant_id, lesson_count=1, title="Бариста-базовый")
    # Правило создано ПОСЛЕ старого профиля.
    rule = AutomationRule(
        tenant_id=tenant_id,
        title="Курс бариста",
        trigger="position_assigned",
        position_ids=[pos.id],
        course_id=course.id,
        applies_from=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(rule)
    await db.flush()
    old_profile.position_id = pos.id
    await db.flush()

    # Ветеран (created_at < applies_from) не попадает — ретро-защита.
    assert await _materialize(db, rule) == 0

    # Новый профиль с нужной должностью — попадает.
    _new_member, new_profile = await _mk_member(db, tenant_id, email="rookie@t.ru")
    new_profile.position_id = pos.id
    await db.flush()
    assert await _materialize(db, rule) == 1

    # Без должности из списка — не попадает.
    _other, _other_profile = await _mk_member(db, tenant_id, email="other@t.ru")
    assert await _materialize(db, rule) == 0


async def test_archive_cancels_pending_jobs(db: AsyncSession, tenant_id: uuid.UUID):
    _member, profile = await _mk_member(db, tenant_id, email="leaving@t.ru")
    course, _ = await _mk_course(db, tenant_id, lesson_count=1)
    rule = AutomationRule(
        tenant_id=tenant_id,
        title="R",
        trigger="profile_activated",
        course_id=course.id,
        applies_from=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(rule)
    await db.flush()
    await _materialize(db, rule)

    await archive_profile(db, profile, reason="manual", actor_id=None)
    await db.flush()

    job = (
        await db.execute(select(AutomationJob).where(AutomationJob.profile_id == profile.id))
    ).scalar_one()
    assert job.status == "cancelled"


async def test_inactivity_warn_then_archive(db: AsyncSession, tenant_id: uuid.UUID):
    _member, profile = await _mk_member(db, tenant_id, email="sleepy@t.ru")
    profile.last_activity_at = datetime.now(UTC) - timedelta(days=120)
    await db.flush()

    stats = await _process_tenant(db, tenant_id)
    assert stats["warned"] >= 1
    await db.flush()

    async def _state() -> tuple:
        return (
            await db.execute(
                select(
                    EmployeeProfile.inactivity_warned_at,
                    EmployeeProfile.status,
                    EmployeeProfile.archive_reason,
                ).where(EmployeeProfile.id == profile.id)
            )
        ).one()

    warned_at, prof_status, _ = await _state()
    assert warned_at is not None

    # Grace ещё не истёк — второй прогон не архивирует.
    await _process_tenant(db, tenant_id)
    await db.flush()
    _, prof_status, _ = await _state()
    assert prof_status == "active"

    # Отматываем warn назад дальше grace-периода → архив.
    profile.inactivity_warned_at = datetime.now(UTC) - timedelta(days=5)
    await db.flush()
    stats3 = await _process_tenant(db, tenant_id)
    assert stats3["archived"] >= 1
    await db.flush()
    _, prof_status, reason = await _state()
    assert prof_status == "archived"
    assert reason == "auto_inactivity"


async def test_inactivity_reset_on_activity(db: AsyncSession, tenant_id: uuid.UUID):
    _member, profile = await _mk_member(db, tenant_id, email="returned@t.ru")
    profile.last_activity_at = datetime.now(UTC)
    profile.inactivity_warned_at = datetime.now(UTC) - timedelta(days=2)
    await db.flush()

    stats = await _process_tenant(db, tenant_id)
    assert stats["reset"] >= 1
    await db.flush()
    assert profile.inactivity_warned_at is None
    assert profile.status == "active"


async def test_learn_search_finds_published(db: AsyncSession, tenant_id: uuid.UUID):
    from app.api.learn_search import learn_search
    from app.services.search_indexer import upsert_document

    member, _profile = await _mk_member(db, tenant_id, email="searcher@t.ru")
    object_id = uuid.uuid4()
    await upsert_document(
        db,
        tenant_id=tenant_id,
        object_type="library_material",
        object_id=object_id,
        title="Регламент возврата товара",
        snippet="Как оформить возврат от гостя",
        url_path=f"/learn/library?m={object_id}",
        published_at=datetime.now(UTC),
    )
    await db.flush()

    resp = await learn_search("возврат", member, db)
    assert resp.total >= 1
    assert any(h.object_id == object_id for h in resp.hits)

    from app.models.engagement import SearchQueryLog

    logged = (
        await db.execute(
            select(SearchQueryLog).where(SearchQueryLog.query == "возврат")
        )
    ).scalars().all()
    assert len(logged) >= 1


async def test_analytics_scope_and_403(db: AsyncSession, tenant_id: uuid.UUID):
    from fastapi import HTTPException

    from app.api.learn_analytics import analytics

    member, profile = await _mk_member(db, tenant_id, email="lineworker@t.ru")
    # Линейному сотруднику аналитика недоступна.
    with pytest.raises(HTTPException) as exc:
        await analytics(member, db)
    assert exc.value.status_code == 403

    # Publisher видит всю сеть.
    profile.content_role = "publisher"
    await db.flush()
    resp = await analytics(member, db)
    assert resp.scope == "all"
    assert resp.overview.employees_total >= 1
