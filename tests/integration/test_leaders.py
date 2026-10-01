"""«Команда за 30 дней» — семантика рейтинга, которую компиляция SQL не ловит.

Фан-аут по исполнителям, личное пространство, сервисная учётка, ничья по
имени, моё место вне тройки и сходимость ряда «создано» с плиткой.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.api.stats import get_leaders, get_my_stats
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.models.task import TaskAssignee
from tests.integration.conftest import make_principal
from tests.integration.test_stats_search import _add_task, _seed_project

pytestmark = pytest.mark.integration


async def _shadow(db, principal, *, account_kind=None):
    db.add(
        ShadowUser(
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            email=principal.email,
            full_name=principal.full_name,
            account_kind=account_kind,
        )
    )
    await db.flush()


async def _assign(db, task, principal, position=1):
    db.add(
        TaskAssignee(
            task_id=task.id,
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            position=position,
        )
    )
    await db.flush()


async def test_leaders_fanout_personal_service_and_me(db, tenant_id):
    me = make_principal(tenant_id, role="member", email="me@test.ru", full_name="Яков Я")
    project, _ = await _seed_project(db, me)  # одна открытая задача, created_by=me
    now = datetime.now(UTC)

    anna = make_principal(tenant_id, email="anna@test.ru", full_name="Анна А")
    boris = make_principal(tenant_id, email="boris@test.ru", full_name="Борис Б")
    kassa = make_principal(tenant_id, email="kassa@test.ru", full_name="Касса 1")
    for p in (anna, boris):
        await _shadow(db, p)
    await _shadow(db, kassa, account_kind="service")

    # Закрытая задача с ДВУМЯ исполнителями — считается обоим (фан-аут).
    t = await _add_task(db, me, project, seq=2, done=True, completed_at=now - timedelta(days=2))
    await _assign(db, t, anna)
    # Ещё одна закрытая — только Анне: она первая, у меня и Бориса по одной.
    t2 = await _add_task(db, me, project, seq=3, mine=False, done=True,
                         completed_at=now - timedelta(days=3))
    await _assign(db, t2, anna, position=0)
    t3 = await _add_task(db, me, project, seq=4, mine=False, done=True,
                         completed_at=now - timedelta(days=4))
    await _assign(db, t3, boris, position=0)
    # Касса закрыла три — в рейтинг не попадает.
    for seq in (5, 6, 7):
        tk = await _add_task(db, me, project, seq=seq, mine=False, done=True,
                             completed_at=now - timedelta(days=1))
        await _assign(db, tk, kassa, position=0)
    # Старое закрытие — вне окна.
    await _add_task(db, me, project, seq=8, done=True, completed_at=now - timedelta(days=40))
    # Просрочено: у Бориса две, у меня одна.
    for seq in (9, 10):
        tb = await _add_task(db, me, project, seq=seq, mine=False, due_at=now - timedelta(days=3))
        await _assign(db, tb, boris, position=0)
    await _add_task(db, me, project, seq=11, due_at=now - timedelta(days=2))

    # Личное пространство: закрытые заметки в рейтинг не идут.
    personal = Project(
        tenant_id=tenant_id, key="PERS", name="Личное", created_by=me.employee_id,
        personal_owner_id=me.employee_id,
    )
    db.add(personal)
    await db.flush()
    for seq in (1, 2, 3, 4):
        await _add_task(db, me, personal, seq=seq, done=True,
                        completed_at=now - timedelta(days=1))

    out = await get_leaders(principal=me, db=db)
    assert out.window_days == 30
    # Выполнили: Анна 2, затем ничья 1:1 по имени — Борис Б, Яков Я (я).
    assert [(lead.full_name, lead.count, lead.rank) for lead in out.completed] == [
        ("Анна А", 2, 1), ("Борис Б", 1, 2), ("Яков Я", 1, 3),
    ]
    assert out.me.completed is not None and out.me.completed.rank == 3
    # Создали: все задачи завёл я (личные не считаются): фикстура + 10 рабочих.
    assert out.created[0].full_name == "Яков Я"
    assert out.created[0].count == 11
    assert out.me.created is not None and out.me.created.rank == 1
    # Просрочено сейчас: Борис 2, я 1.
    assert [(lead.full_name, lead.count) for lead in out.overdue] == [("Борис Б", 2), ("Яков Я", 1)]
    assert out.me.overdue is not None and out.me.overdue.rank == 2
    # Касса нигде.
    names = {lead.full_name for col in (out.completed, out.created, out.overdue) for lead in col}
    assert "Касса 1" not in names


async def test_me_none_when_zero_and_created_series_matches_counter(db, tenant_id):
    me = make_principal(tenant_id, role="member")
    project, _ = await _seed_project(db, me)
    await _add_task(db, me, project, seq=2, mine=False)  # ещё одна заведённая мной

    out = await get_leaders(principal=me, db=db)
    assert out.completed == [] and out.me.completed is None
    assert out.overdue == [] and out.me.overdue is None
    assert out.me.created is not None and out.me.created.count == 2

    stats = await get_my_stats(principal=me, db=db)
    assert sum(p.created for p in stats.daily) == stats.created_30 == 2
    assert stats.daily[-1].created == 2
