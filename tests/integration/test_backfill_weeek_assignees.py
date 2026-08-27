"""Проход 2: доставить исполнителей, когда люди появятся в Hub.

Две вещи, ради которых этот проход вообще существует отдельно: он не должен
разослать пачку «Вам назначена задача» про задачи 2022 года и не должен
затереть то, что человек успел поправить руками.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.backfill_weeek_assignees import Backfill
from app.jobs.import_weeek_bundle import Importer
from app.jobs.weeek_common import KIND_TASK, hub_id
from app.models.notification import Notification
from app.models.project import ProjectMember
from app.models.task import Task, TaskAssignee, TaskWatcher
from tests.integration.conftest import make_principal
from tests.integration.test_import_weeek import attachments_root, write_bundle  # noqa: F401
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

# У этой задачи в бандле исполнитель, которого в Hub ещё нет.
UNKNOWN_TASK = 104


@pytest.fixture
async def staged(db: AsyncSession, tenant_id: uuid.UUID, tmp_path: Path, attachments_root):  # noqa: F811
    """Импорт уже прошёл; «Андрей Доценко» в Hub ещё не заходил."""
    slug = f"bf-{uuid.uuid4().hex[:8]}"
    actor = make_principal(tenant_id, email=f"actor-{slug}@t.ru", tenant_slug=slug)
    mate = make_principal(tenant_id, email=f"mate-{slug}@t.ru", tenant_slug=slug)
    await _register(db, actor, org_role="office")
    await _register(db, mate)
    await db.commit()
    # Адрес уникален на тест: под superuser RLS не режет, и джоба видит
    # shadow_users всех тенантов (см. write_bundle).
    unknown_email = f"unknown-{slug}@t.ru"
    bundle = write_bundle(tmp_path, known_email=mate.email, unknown_email=unknown_email)
    await Importer(bundle, tenant_id=tenant_id, actor_id=actor.employee_id, apply=True).run(db)
    return {
        "bundle": bundle, "actor": actor, "tenant_id": tenant_id,
        "unknown_email": unknown_email,
    }


async def _arrive(db: AsyncSession, staged: dict) -> uuid.UUID:
    """«Андрей Доценко» наконец зашёл в Hub."""
    late = make_principal(
        staged["tenant_id"], email=staged["unknown_email"], full_name="Андрей Доценко",
        tenant_slug=f"late-{uuid.uuid4().hex[:8]}",
    )
    await _register(db, late)
    await db.commit()
    return late.employee_id


async def _run(db: AsyncSession, staged: dict, *, apply: bool = True) -> Backfill:
    job = Backfill(
        staged["bundle"], tenant_id=staged["tenant_id"],
        actor_id=staged["actor"].employee_id, apply=apply,
    )
    await job.run(db)
    return job


async def _task(db: AsyncSession, staged: dict) -> Task:
    return await db.get(Task, hub_id(staged["tenant_id"], KIND_TASK, UNKNOWN_TASK))


class TestArrival:
    async def test_assignee_membership_and_note_removed(self, db: AsyncSession, staged):
        employee_id = await _arrive(db, staged)
        task_before = await _task(db, staged)
        assert "_Исполнитель в WEEEK: Андрей Доценко_" in task_before.description

        job = await _run(db, staged)
        assert job.stats["исполнителей проставлено"] == 1

        task = await _task(db, staged)
        assert "Исполнитель в WEEEK" not in task.description
        # Остальной блок провенанса на месте — сняли ровно одну строку.
        assert "Вложения в WEEEK: видео.mov." in task.description

        assignees = (
            await db.execute(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
        ).scalars().all()
        assert [a.employee_id for a in assignees] == [employee_id]

        member = (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == task.project_id,
                    ProjectMember.employee_id == employee_id,
                )
            )
        ).scalar_one()
        assert member.role == "viewer"  # назначение даёт минимальный доступ

    async def test_no_notifications(self, db: AsyncSession, staged):
        await _arrive(db, staged)
        await _run(db, staged)
        count = (
            await db.execute(
                select(func.count()).select_from(Notification)
                .where(Notification.tenant_id == staged["tenant_id"])
            )
        ).scalar_one()
        assert count == 0

    async def test_open_task_gets_a_watcher(self, db: AsyncSession, staged):
        await _arrive(db, staged)
        await _run(db, staged)
        task = await _task(db, staged)
        watchers = (
            await db.execute(select(TaskWatcher).where(TaskWatcher.task_id == task.id))
        ).scalars().all()
        assert [w.added_reason for w in watchers] == ["assignee"]

    async def test_second_run_is_a_noop(self, db: AsyncSession, staged):
        await _arrive(db, staged)
        await _run(db, staged)
        again = await _run(db, staged)
        assert again.stats["задач обновлено"] == 0
        assert again.stats["пропущено: исполнитель уже есть"] >= 1

    async def test_nobody_arrived_yet(self, db: AsyncSession, staged):
        job = await _run(db, staged)
        assert job.stats["задач обновлено"] == 0
        assert job.still_missing[staged["unknown_email"]] == 1
        task = await _task(db, staged)
        assert "_Исполнитель в WEEEK: Андрей Доценко_" in task.description


class TestManualEdits:
    async def test_edited_body_keeps_the_edit_and_loses_the_note(
        self, db: AsyncSession, staged
    ):
        await _arrive(db, staged)
        task = await _task(db, staged)
        task.description = task.description.replace("Тело", "Тело, дополненное руками")
        await db.commit()

        job = await _run(db, staged)
        assert job.stats["описаний очищено после ручной правки"] == 1
        updated = await _task(db, staged)
        assert "дополненное руками" in updated.description
        assert "Исполнитель в WEEEK" not in updated.description

    async def test_rewritten_description_is_not_touched(self, db: AsyncSession, staged):
        await _arrive(db, staged)
        task = await _task(db, staged)
        task.description = "Полностью переписал"
        await db.commit()

        job = await _run(db, staged)
        assert job.stats["описаний не тронуто (переписаны вручную)"] == 1
        updated = await _task(db, staged)
        assert updated.description == "Полностью переписал"
        # Исполнителя при этом всё равно проставили — это независимая ось.
        assert job.stats["исполнителей проставлено"] == 1

    async def test_manual_assignment_is_never_overwritten(self, db: AsyncSession, staged):
        # `set_task_assignees` — replace-семантика: без гейта проход стёр бы
        # того, кого поставили руками.
        arrived = await _arrive(db, staged)
        task = await _task(db, staged)
        db.add(
            TaskAssignee(
                task_id=task.id,
                employee_id=staged["actor"].employee_id,
                tenant_id=staged["tenant_id"],
                position=0,
            )
        )
        await db.commit()

        job = await _run(db, staged)
        assert job.stats["пропущено: исполнитель уже есть"] >= 1
        rows = (
            await db.execute(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
        ).scalars().all()
        assert [a.employee_id for a in rows] == [staged["actor"].employee_id]
        assert arrived not in {a.employee_id for a in rows}


class TestDryRun:
    async def test_nothing_is_written(self, db: AsyncSession, staged):
        await _arrive(db, staged)
        job = await _run(db, staged, apply=False)
        await db.rollback()
        assert job.stats["задач обновлено"] == 1

        task = await _task(db, staged)
        assert "_Исполнитель в WEEEK: Андрей Доценко_" in task.description
        assignees = await db.execute(
            select(func.count()).select_from(TaskAssignee)
            .where(TaskAssignee.task_id == task.id)
        )
        assert assignees.scalar_one() == 0
