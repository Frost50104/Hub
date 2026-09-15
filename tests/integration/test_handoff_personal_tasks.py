"""Разовая джоба: живые задачи уезжают в личное своих исполнителей.

Состояние, которое она разбирает, через API больше не создаётся (с 15.09
назначение коллеги переносит задачу сразу), поэтому легаси-строки тест
собирает руками — ровно так они и лежат на проде.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tasks import get_task
from app.jobs.handoff_personal_tasks import handoff_tenant
from app.models.project import ProjectMember
from app.models.task import Task, TaskAssignee, TaskWatcher
from app.schemas.task import TaskCreate
from app.services.personal_projects import ensure_personal_project
from app.services.stages import set_done
from app.services.task_assignees import set_task_assignees
from app.services.tasks import create_task_record
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _member(db: AsyncSession, tenant_id: uuid.UUID, slug: str) -> Principal:
    principal = make_principal(
        tenant_id, email=f"{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, principal, org_role="office")
    return principal


async def _legacy_task(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    owner: Principal,
    title: str,
    assignees: list[uuid.UUID],
    parent_task_id: uuid.UUID | None = None,
) -> Task:
    """Задача в личном владельца с ЧУЖИМ исполнителем — состояние до 15.09.

    Мимо ручек: `apply_personal_assignee_rules` такую строку сегодня же
    перенесла бы, и собрать «как было» через API невозможно.
    """
    task = await create_task_record(
        db,
        principal=owner,
        project_id=project_id,
        body=TaskCreate(title=title, parent_task_id=parent_task_id, assignee_ids=[]),
    )
    await db.flush()
    await set_task_assignees(
        db, task=task, employee_ids=assignees, actor_id=owner.employee_id
    )
    await db.commit()
    return task


async def test_job_moves_live_task_and_keeps_author_in_the_loop(db, tenant_id):
    owner = await _member(db, tenant_id, "hj-owner")
    mate = await _member(db, tenant_id, "hj-mate")
    mine = await ensure_personal_project(db, owner)
    theirs = await ensure_personal_project(db, mate)
    await db.commit()
    task = await _legacy_task(
        db,
        project_id=mine,
        owner=owner,
        title="Доделки БМ5",
        assignees=[mate.employee_id],
    )

    dry = await handoff_tenant(db, tenant_id, apply=False)
    assert len(dry.moved) == 1 and "Доделки БМ5" in dry.moved[0]
    # Разбор ничего не пишет: задача на месте.
    assert (await db.get(Task, task.id)).project_id == mine

    report = await handoff_tenant(db, tenant_id, apply=True)
    await db.commit()
    assert len(report.moved) == 1

    moved = await db.get(Task, task.id)
    assert moved.project_id == theirs
    # Автор не теряет свою задачу: подписка + членство, как на живом пути.
    watchers = set(
        (
            await db.execute(
                select(TaskWatcher.employee_id).where(TaskWatcher.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    assert owner.employee_id in watchers
    members = set(
        (
            await db.execute(
                select(ProjectMember.employee_id).where(
                    ProjectMember.project_id == theirs
                )
            )
        )
        .scalars()
        .all()
    )
    assert owner.employee_id in members
    # `updated_at` проставил сервер — в тестовой сессии объект после UPDATE
    # ждёт refresh'а (на живом пути его делает сама ручка).
    await db.refresh(moved)
    assert (await get_task(task.id, owner, db)).id == task.id

    # Второй прогон не находит работы — джоба идемпотентна по построению.
    assert (await handoff_tenant(db, tenant_id, apply=True)).moved == []


async def test_job_leaves_history_and_ambiguity_alone(db, tenant_id):
    """Выполненные, многолюдные, подзадачи и «некуда везти» — не трогаем."""
    owner = await _member(db, tenant_id, "hj2-owner")
    mate = await _member(db, tenant_id, "hj2-mate")
    other = await _member(db, tenant_id, "hj2-other")
    newbie = await _member(db, tenant_id, "hj2-newbie")  # ни разу не заходил
    mine = await ensure_personal_project(db, owner)
    await ensure_personal_project(db, mate)
    await ensure_personal_project(db, other)
    await db.commit()

    done = await _legacy_task(
        db, project_id=mine, owner=owner, title="Прогрузить макеты",
        assignees=[mate.employee_id],
    )
    set_done(done, True)
    crowd = await _legacy_task(
        db, project_id=mine, owner=owner, title="Добавить сотрудников",
        assignees=[mate.employee_id, other.employee_id],
    )
    parent = await _legacy_task(
        db, project_id=mine, owner=owner, title="Ремонт", assignees=[]
    )
    child = await _legacy_task(
        db, project_id=mine, owner=owner, title="Вызвать мастера",
        assignees=[mate.employee_id], parent_task_id=parent.id,
    )
    nowhere = await _legacy_task(
        db, project_id=mine, owner=owner, title="Принять смену",
        assignees=[newbie.employee_id],
    )
    await db.commit()

    report = await handoff_tenant(db, tenant_id, apply=True)
    await db.commit()
    assert report.moved == []
    reasons = {label.split("«")[1].rstrip("»"): why for label, why in report.skipped}
    assert reasons == {
        "Добавить сотрудников": "исполнителей больше одного",
        "Вызвать мастера": "подзадача — едет только с родителем",
        "Принять смену": "у исполнителя нет личного пространства",
    }
    # Выполненная в отчёт не попадает вовсе — её не рассматривали.
    for task_id in (done.id, crowd.id, child.id, nowhere.id):
        assert (await db.get(Task, task_id)).project_id == mine
    # И исполнители у них те же.
    kept = (
        await db.execute(
            select(TaskAssignee.employee_id).where(TaskAssignee.task_id == done.id)
        )
    ).scalars().all()
    assert list(kept) == [mate.employee_id]
