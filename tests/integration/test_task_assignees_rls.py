"""RLS на task_assignees (0034) — обязательный тест для новой доменной таблицы.

Пропуск политики на link-таблице уже случался: `task_label_assignments` в 0003
создали без tenant_id и без policy, чинили миграцией 0011. Этот тест не даёт
повторить историю.

Под `rls_enforced` (non-superuser роль): под superuser'ом testcontainers RLS
не применяется вовсе, и тест молча выродился бы в no-op.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.db import tenant_scoped_session

pytestmark = pytest.mark.integration


async def _seed_task_with_assignee(tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Проект + задача + назначение в указанном tenant'е (через bypass)."""
    employee_id = uuid.uuid4()
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    async with tenant_scoped_session(None, bypass_rls=True) as s:
        await s.execute(
            text(
                "INSERT INTO shadow_tenants (id, slug, name, status) "
                "VALUES (:tid, :slug, 'T', 'active') ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": tenant_id, "slug": f"t-{tenant_id.hex[:12]}"},
        )
        await s.execute(
            text(
                "INSERT INTO shadow_users (employee_id, tenant_id, email, full_name) "
                "VALUES (:eid, :tid, :email, 'N')"
            ),
            {
                "eid": employee_id,
                "tid": tenant_id,
                "email": f"{employee_id.hex[:12]}@test.ru",
            },
        )
        await s.execute(
            text(
                "INSERT INTO projects (id, tenant_id, key, name, created_by) "
                "VALUES (:pid, :tid, :key, 'P', :eid)"
            ),
            {
                "pid": project_id,
                "tid": tenant_id,
                "key": f"K{project_id.hex[:6].upper()}",
                "eid": employee_id,
            },
        )
        await s.execute(
            text(
                "INSERT INTO tasks (id, tenant_id, project_id, title, created_by, "
                "position, seq) VALUES (:id, :tid, :pid, 'Задача', :eid, 1, 1)"
            ),
            {"id": task_id, "tid": tenant_id, "pid": project_id, "eid": employee_id},
        )
        await s.execute(
            text(
                "INSERT INTO task_assignees (task_id, employee_id, tenant_id, position) "
                "VALUES (:tid_task, :eid, :tid, 0)"
            ),
            {"tid_task": task_id, "eid": employee_id, "tid": tenant_id},
        )
        await s.commit()
    return task_id, employee_id


@pytest.mark.asyncio
async def test_task_assignees_rls_isolates_tenants(rls_enforced) -> None:
    """Свои назначения видны, чужие — нет.

    Второй ассерт заодно доказывает, что RLS на таблице реально включён:
    без политики (или без FORCE) он падает, а не проходит.
    """
    mine_tenant = uuid.uuid4()
    other_tenant = uuid.uuid4()
    mine_task, _ = await _seed_task_with_assignee(mine_tenant)
    other_task, _ = await _seed_task_with_assignee(other_tenant)

    async with tenant_scoped_session(mine_tenant) as s:
        visible = set(
            (
                await s.execute(
                    text(
                        "SELECT task_id FROM task_assignees WHERE task_id IN (:a, :b)"
                    ),
                    {"a": mine_task, "b": other_task},
                )
            )
            .scalars()
            .all()
        )
    assert mine_task in visible
    assert other_task not in visible
