"""Разовая джоба: «Личное»/LICNOE → «Мои задачи»/ключ из ФИО.

Смена констант действует только на новых сотрудников — существующим 178
проектам имя и ключ меняет эта джоба. Ключ user-visible (он в номере каждой
задачи), поэтому проверяем не только результат, но и то, что повторный прогон
ничего не делает, а осознанно выбранное имя не затирается.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.rename_personal_projects import OLD_NAME, rename_tenant
from app.models.project import Project
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.services.personal_projects import (
    PERSONAL_PROJECT_NAME,
    ensure_personal_project,
    personal_key_base,
)
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _legacy_personal(
    db: AsyncSession, tenant_id: uuid.UUID, slug: str, full_name: str
) -> tuple[Principal, Project]:
    """Личный проект «как до 16.09»: имя «Личное», ключ LICNOE*."""
    principal = make_principal(
        tenant_id, email=f"{slug}@t.ru", full_name=full_name, tenant_slug=slug
    )
    await _register(db, principal, org_role="office")
    project_id = await ensure_personal_project(db, principal)
    project = await db.get(Project, project_id)
    project.name = OLD_NAME
    project.key = f"LICNOE{uuid.uuid4().int % 1000}"
    await db.commit()
    return principal, project


async def test_renames_and_rekeys(db, tenant_id):
    owner, project = await _legacy_personal(db, tenant_id, "rn-a", "Пётр Попов")
    old_key = project.key

    report = await rename_tenant(db, tenant_id, apply=True)
    await db.commit()

    assert report.renamed and report.rekeyed
    fresh = await db.get(Project, project.id)
    assert fresh.name == PERSONAL_PROJECT_NAME
    assert fresh.key == personal_key_base(owner.full_name) == "PETRPOPOV"
    assert fresh.key != old_key


async def test_dry_run_writes_nothing(db, tenant_id):
    _owner, project = await _legacy_personal(db, tenant_id, "rn-dry", "Анна Иванова")
    old = (project.key, project.name)

    report = await rename_tenant(db, tenant_id, apply=False)
    assert report.rekeyed  # отчёт есть

    fresh = await db.get(Project, project.id)
    assert (fresh.key, fresh.name) == old


async def test_second_run_is_noop(db, tenant_id):
    """Идемпотентность: ключ уже в целевом виде — трогать нечего."""
    _owner, _project = await _legacy_personal(db, tenant_id, "rn-twice", "Иван Сидоров")
    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()

    again = await rename_tenant(db, tenant_id, apply=True)
    await db.commit()
    assert again.rekeyed == []
    assert again.renamed == []


async def test_namesakes_get_stable_suffixes(db, tenant_id):
    """Тёзки получают base и base2 — и на повторном прогоне не меняются местами."""
    _a, first = await _legacy_personal(db, tenant_id, "rn-t1", "Мария Смирнова")
    _b, second = await _legacy_personal(db, tenant_id, "rn-t2", "Мария Смирнова")

    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()
    keys = [(await db.get(Project, p.id)).key for p in (first, second)]
    assert sorted(keys) == ["MARIYASMIRNOV", "MARIYASMIRNOV2"]

    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()
    assert [(await db.get(Project, p.id)).key for p in (first, second)] == keys


async def test_key_taken_by_work_project(db, tenant_id):
    """Namespace ключей общий — занятый рабочим проектом уводит в суффикс."""
    from app.api.projects import create_project

    owner, project = await _legacy_personal(db, tenant_id, "rn-busy", "Олег Орлов")
    base = personal_key_base(owner.full_name)
    await create_project(ProjectCreate(name="Рабочий", key=base), owner, db)
    await db.commit()

    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()
    fresh = await db.get(Project, project.id)
    assert fresh.key == f"{base}2"


async def test_manual_name_is_not_overwritten(db, tenant_id):
    """Человек переименовал личное сам — джоба не спорит, а рапортует."""
    _owner, project = await _legacy_personal(db, tenant_id, "rn-manual", "Лев Волков")
    project.name = "Мой инбокс"
    await db.commit()

    report = await rename_tenant(db, tenant_id, apply=True)
    await db.commit()
    assert (await db.get(Project, project.id)).name == "Мой инбокс"
    assert any("Мой инбокс" in why for _label, why in report.skipped)


async def test_task_numbering_is_untouched(db, tenant_id):
    """Меняется печатаемый префикс, а не нумерация: `seq` и счётчик на месте."""
    from app.api.tasks import create_task

    owner, project = await _legacy_personal(db, tenant_id, "rn-seq", "Нина Зайцева")
    task = await create_task(project.id, TaskCreate(title="Купить хлеб"), owner, db)
    await db.commit()
    before = ((await db.get(Task, task.id)).seq, (await db.get(Project, project.id)).next_task_seq)

    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()

    fresh = await db.get(Project, project.id)
    assert ((await db.get(Task, task.id)).seq, fresh.next_task_seq) == before


async def test_manual_key_override(db, tenant_id):
    """`--employee … --key …` — единственный способ поправить ключ вообще."""
    owner, project = await _legacy_personal(db, tenant_id, "rn-force", "Юлия Белокрылова")

    await rename_tenant(
        db, tenant_id, apply=True, only_employee=owner.employee_id, forced_key="BELOKRYLOVA"
    )
    await db.commit()
    assert (await db.get(Project, project.id)).key == "BELOKRYLOVA"


async def test_audit_records_the_change(db, tenant_id):
    """Массовая правка user-visible ключей обязана оставить след."""
    from app.models.audit import AuditLog

    _owner, project = await _legacy_personal(db, tenant_id, "rn-audit", "Вера Павлова")
    await rename_tenant(db, tenant_id, apply=True)
    await db.commit()

    rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.object_type == "project", AuditLog.object_id == project.id
            )
        )
    ).scalars().all()
    assert rows and rows[-1].diff.get("key")
    # actor_id=None — «инициатор не человек», как у переименований из фида auth.
    assert rows[-1].actor_id is None
