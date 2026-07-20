"""Регресс-тесты /search и /projects/{id}/stats.

Оба эндпоинта молча ломались обновлением SQLAlchemy (dependabot), а CI не
замечал: stats собирал CAST с NullType (CompileError), search передавал объект
func.websearch_to_tsquery bind-параметром (asyncpg DataError). Тесты фиксируют
исполнимость SQL и базовую корректность ответов.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.project import Project, ProjectMember
from app.models.shadow import ShadowUser
from app.models.task import Task

pytestmark = pytest.mark.integration

OPT_A = "11111111-1111-1111-1111-111111111111"


async def _seed_project(db, principal):
    db.add(
        ShadowUser(
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            email=principal.email,
            full_name=principal.full_name,
        )
    )
    await db.flush()
    project = Project(
        tenant_id=principal.tenant_id,
        key="QP",
        name="QA регрессия",
        created_by=principal.employee_id,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            employee_id=principal.employee_id,
            role="owner",
        )
    )
    task = Task(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        title="Проверить онбординг новых сотрудников",
        description="Чек-лист онбординга и выдача доступов",
        status="in_progress",
        priority="high",
        assignee_id=principal.employee_id,
        created_by=principal.employee_id,
        position=Decimal(1),
    )
    db.add(task)
    await db.flush()
    return project, task


async def test_search_fts_grouped_and_legacy(db, tenant_id):
    """FTS-ветка (websearch_to_tsquery) исполняется и находит задачу."""
    from app.api.search import search
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, task = await _seed_project(db, principal)

    grouped = await search(
        q="онбординг assignee:me", group_by="project", principal=principal, db=db
    )
    assert grouped.total == 1
    assert grouped.groups[0].tasks[0].id == task.id

    legacy = await search(q="онбординг", group_by=None, principal=principal, db=db)
    assert any(hit.id == task.id for hit in legacy.tasks)


async def test_project_stats_workload_and_cf(db, tenant_id):
    """stats: workload-CAST'ы и CF-агрегаты (number float8, select text)."""
    from app.api.stats import get_stats
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, task = await _seed_project(db, principal)

    num_def = CustomFieldDefinition(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        name="Бюджет",
        type="number",
        options=[],
        position=Decimal(1),
    )
    sel_def = CustomFieldDefinition(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        name="Магазин",
        type="select",
        options=[{"id": OPT_A, "label": "П14"}],
        position=Decimal(2),
    )
    db.add_all([num_def, sel_def])
    await db.flush()
    db.add_all(
        [
            TaskCustomFieldValue(
                tenant_id=principal.tenant_id,
                task_id=task.id,
                field_id=num_def.id,
                value=1500,
            ),
            TaskCustomFieldValue(
                tenant_id=principal.tenant_id,
                task_id=task.id,
                field_id=sel_def.id,
                value=OPT_A,
            ),
        ]
    )
    await db.flush()

    stats = await get_stats(project_id=project.id, principal=principal, db=db)

    my_row = next(
        w for w in stats.workload if w.employee_id == principal.employee_id
    )
    assert my_row.active_count == 1
    assert my_row.done_count == 0

    by_name = {cf.name: cf for cf in stats.custom_field_stats}
    assert by_name["Бюджет"].number.sum == 1500
    opt_counts = {o.id: o.count for o in by_name["Магазин"].select.options}
    assert opt_counts[OPT_A] == 1
