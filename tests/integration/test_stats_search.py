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
from app.models.stage import ProjectStage
from app.models.task import Task, TaskAssignee

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
    # Фикстура конструирует проект напрямую, минуя create_project_record, —
    # колонки доски создаём сами: тест проверяет срез статистики ПО колонкам,
    # а сам проект их больше не заводит (26.08).
    stages = [
        ProjectStage(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            name=name,
            position=position,
        )
        for position, name in enumerate(("К выполнению", "В работе", "На проверке", "Готово"))
    ]
    for stage in stages:
        db.add(stage)
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
        stage_id=stages[1].id,
        title="Проверить онбординг новых сотрудников",
        description="Чек-лист онбординга и выдача доступов",
        priority="high",
        created_by=principal.employee_id,
        position=Decimal(1),
        seq=1,
    )
    db.add(task)
    await db.flush()
    # Исполнители живут только в task_assignees (0034); фикстура конструирует
    # Task напрямую, минуя set_task_assignees, поэтому пишет строку сама.
    db.add(
        TaskAssignee(
            task_id=task.id,
            employee_id=principal.employee_id,
            tenant_id=principal.tenant_id,
            position=0,
        )
    )
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


# ─── GET /api/me/stats ──────────────────────────────────────────────────────
# Та же мотивация, что у всего файла: ручка собирает CAST'ы и date_trunc по
# timezone(), и молчаливая поломка после апгрейда SQLAlchemy видна только на
# исполнении. Сессия не коммитится — читаем через неё же, хватает flush.


async def _add_task(db, principal, project, *, seq, mine=True, **fields):
    """Ещё одна задача в проекте фикстуры. `mine=False` — без исполнителя."""
    from sqlalchemy import select as sa_select


    stage_id = (
        await db.execute(
            sa_select(ProjectStage.id)
            .where(ProjectStage.project_id == project.id)
            .order_by(ProjectStage.position)
        )
    ).scalars().first()
    task = Task(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        stage_id=stage_id,
        title=f"Задача {seq}",
        priority="medium",
        created_by=principal.employee_id,
        position=Decimal(seq),
        seq=seq,
        **fields,
    )
    db.add(task)
    await db.flush()
    if mine:
        db.add(
            TaskAssignee(
                task_id=task.id,
                employee_id=principal.employee_id,
                tenant_id=principal.tenant_id,
                position=0,
            )
        )
        await db.flush()
    return task


async def test_my_stats_windows_and_daily(db, tenant_id):
    """Оба окна одним ответом, `daily` — ровно 30 точек, последняя сегодня."""
    from datetime import UTC, datetime, timedelta

    from app.api.stats import get_my_stats
    from app.services.taskdates import display_today
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, _ = await _seed_project(db, principal)

    now = datetime.now(UTC)
    # Вчера — в оба окна; 10 дней назад — только в 30; 40 — ни в одно.
    await _add_task(db, principal, project, seq=2, done=True,
                    completed_at=now - timedelta(days=1))
    await _add_task(db, principal, project, seq=3, done=True,
                    completed_at=now - timedelta(days=10))
    await _add_task(db, principal, project, seq=4, done=True,
                    completed_at=now - timedelta(days=40))

    stats = await get_my_stats(principal=principal, db=db)
    assert stats.completed_7 == 1
    assert stats.completed_30 == 2
    assert len(stats.daily) == 30
    assert sum(p.count for p in stats.daily) == 2
    # Последняя точка — сегодня: график не должен обрываться вчерашним днём.
    assert stats.daily[-1].day == display_today(now)


async def test_my_stats_counts_only_mine(db, tenant_id):
    """Чужая задача в общем проекте в «выполнено» не попадает.

    А «создано» считается по автору, а не по исполнителю — это ДРУГАЯ
    популяция, и задача без исполнителя туда входит.
    """
    from datetime import UTC, datetime, timedelta

    from app.api.stats import get_my_stats
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, _ = await _seed_project(db, principal)

    now = datetime.now(UTC)
    await _add_task(db, principal, project, seq=2, mine=False, done=True,
                    completed_at=now - timedelta(days=1))

    stats = await get_my_stats(principal=principal, db=db)
    assert stats.completed_7 == 0
    assert stats.created_7 == 2  # задача фикстуры + эта


async def test_my_stats_skips_archived(db, tenant_id):
    """Архивную задачу не считаем — её нет ни на одном экране."""
    from datetime import UTC, datetime, timedelta

    from app.api.stats import get_my_stats
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, _ = await _seed_project(db, principal)

    now = datetime.now(UTC)
    await _add_task(db, principal, project, seq=2, done=True,
                    completed_at=now - timedelta(days=1), archived_at=now)

    stats = await get_my_stats(principal=principal, db=db)
    assert stats.completed_7 == 0
    assert stats.completed_30 == 0


async def test_my_stats_open_and_overdue(db, tenant_id):
    """«В работе» и «просрочено» — состояние на сейчас, окна их не касаются."""
    from datetime import UTC, datetime, timedelta

    from app.api.stats import get_my_stats
    from tests.integration.conftest import make_principal

    principal = make_principal(tenant_id, role="member")
    project, _ = await _seed_project(db, principal)  # 1 открытая без срока

    now = datetime.now(UTC)
    await _add_task(db, principal, project, seq=2, due_at=now - timedelta(days=3))
    await _add_task(db, principal, project, seq=3, done=True,
                    completed_at=now - timedelta(days=100))

    stats = await get_my_stats(principal=principal, db=db)
    assert stats.open_now == 2
    assert stats.overdue_now == 1
