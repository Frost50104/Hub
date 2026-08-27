"""Регресс-тесты пакета ОС тестировщиков 2026-08 (docs/tech-debt/feedback-2026-08.md):
окна «Сегодня/Предстоит/Просрочено» по календарному дню display tz, псевдо-статус
`open`, просрочка в статистике по дням, force-удаление раздела библиотеки с переносом
материалов, текстовый предпросмотр и сохранность body_text при переиндексации."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.library import (
    _reindex,
    create_section,
    delete_section,
    material_text,
)
from app.api.me_tasks import list_my_tasks
from app.api.stats import get_stats
from app.api.tasks import create_task, update_task
from app.models.library import LibrarySection, MaterialVersion
from app.models.search_document import SearchDocument
from app.schemas.library import SectionCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services import taskdates as td
from tests.integration.test_courses import _mk_member
from tests.integration.test_library import _mk_material
from tests.integration.test_quizzes import _mk_publisher
from tests.integration.test_task_multi_assignees import _list, _seed

pytestmark = pytest.mark.integration


async def _my(db, principal, **kw):
    return await list_my_tasks(
        done=kw.get("done"),
        status_=None,
        due_window=kw.get("due_window"),
        include_archived=False,
        principal=principal,
        db=db,
    )


async def test_due_windows_are_calendar_days(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, (a, _b) = await _seed(db, tenant_id, "fb1")
    now = datetime.now(UTC)
    # «Сегодня» по display tz — но мгновение уже в прошлом (через час после
    # начала дня): раньше это считалось просрочкой и выпадало из окон.
    today_past = td.start_of_today_utc(now) + timedelta(minutes=30)
    yesterday = td.due_noon_utc(td.display_today(now) - timedelta(days=1))
    tomorrow = td.due_noon_utc(td.display_today(now) + timedelta(days=1))
    t_today = await create_task(
        project.id, TaskCreate(title="Сегодня", assignee_ids=[a.employee_id], due_at=today_past),
        owner, db,
    )
    t_yesterday = await create_task(
        project.id, TaskCreate(title="Вчера", assignee_ids=[a.employee_id], due_at=yesterday),
        owner, db,
    )
    t_tomorrow = await create_task(
        project.id, TaskCreate(title="Завтра", assignee_ids=[a.employee_id], due_at=tomorrow),
        owner, db,
    )
    closed = await create_task(
        project.id,
        TaskCreate(title="Вчера, готово", assignee_ids=[a.employee_id], due_at=yesterday),
        owner, db,
    )
    await update_task(closed.id, TaskUpdate(done=True), owner, db)

    overdue = {t.id for t in await _my(db, a, due_window="overdue")}
    today = {t.id for t in await _my(db, a, due_window="today")}
    upcoming = {t.id for t in await _my(db, a, due_window="upcoming")}
    assert overdue == {t_yesterday.id}
    # «Сегодня» = просроченные (не done) + срок сегодня (решение владельца).
    assert today == {t_yesterday.id, t_today.id}
    assert upcoming == {t_today.id, t_tomorrow.id}

    # Статистика проекта: сегодняшняя — не просрочка, вчерашняя — да, done — нет.
    stats = await get_stats(project.id, principal=owner, db=db)
    by_id = {w.employee_id: w for w in stats.workload}
    assert by_id[a.employee_id].overdue_count == 1


async def test_done_filter(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project, (a, _b) = await _seed(db, tenant_id, "fb2")
    t_open = await create_task(
        project.id, TaskCreate(title="Открыта", assignee_ids=[a.employee_id]), owner, db
    )
    finished = await create_task(
        project.id, TaskCreate(title="Готова", assignee_ids=[a.employee_id]), owner, db
    )
    await update_task(finished.id, TaskUpdate(done=True), owner, db)
    rows = await _list(db, project.id, owner)
    assert len(rows) == 2
    from app.api.tasks import list_tasks

    open_rows = await list_tasks(

            project.id,
            include_archived=False,
            done=False,
            status_=None,
            assignee_id=None,
            priority=None,
            label=None,
            due_from=None,
            due_to=None,
            sort="position",
            order="asc",
            stage_id=None,
            principal=owner,
            db=db,
        )
    assert [t.id for t in open_rows] == [t_open.id]
    assert [t.id for t in await _my(db, a, done=False)] == [t_open.id]

    # Старый параметр не игнорируется молча, а отвечает 422 (0044).
    with pytest.raises(HTTPException) as exc:
        await list_tasks(

            project.id,
            include_archived=False,
            done=None,
            status_="open",
            assignee_id=None,
            priority=None,
            label=None,
            due_from=None,
            due_to=None,
            sort="position",
            order="asc",
            stage_id=None,
            principal=owner,
            db=db,
        )
    assert exc.value.status_code == 422


async def test_delete_section_force_detaches_materials(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _ = await _mk_publisher(db, tenant_id)
    section = await create_section(SectionCreate(title="Временный"), hr, db)
    child = await create_section(SectionCreate(title="Подраздел", parent_id=section.id), hr, db)
    m1 = await _mk_material(db, tenant_id, title="В разделе", section_id=section.id)
    m2 = await _mk_material(
        db, tenant_id, title="Архивный в разделе", section_id=section.id, status="archived"
    )
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await delete_section(section.id, hr, db)
    assert exc.value.status_code == 409
    assert "2 материалов" in str(exc.value.detail) and "1 подразделов" in str(exc.value.detail)

    await delete_section(section.id, hr, db, force=True)
    assert await db.get(LibrarySection, section.id) is None
    for m in (m1, m2):
        await db.refresh(m)
        assert m.section_id is None
    child_row = await db.get(LibrarySection, child.id)
    assert child_row is not None and child_row.parent_id is None


async def test_material_text_preview_and_reindex_keeps_body(
    db: AsyncSession, tenant_id: uuid.UUID
):
    member, _profile = await _mk_member(db, tenant_id, email="reader@t.ru")
    material = await _mk_material(
        db, tenant_id, title="Техкарта", status="published", published_at=datetime.now(UTC)
    )
    material.current_version_no = 1
    db.add(
        MaterialVersion(
            tenant_id=tenant_id,
            material_id=material.id,
            version_no=1,
            storage_key=f"{tenant_id}/{material.id}/1-t.xlsx",
            file_name="t.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=10,
        )
    )
    await db.flush()

    # Текст ещё не извлечён → 404 с подсказкой.
    with pytest.raises(HTTPException) as exc:
        await material_text(material.id, version=None, principal=member, db=db)
    assert exc.value.status_code == 404

    version = (
        await db.execute(
            select(MaterialVersion).where(MaterialVersion.material_id == material.id)
        )
    ).scalar_one()
    version.extracted_text = "## Лист1\nАзу\t250"
    version.extracted_at = datetime.now(UTC)
    await db.flush()

    resp = await material_text(material.id, version=None, principal=member, db=db)
    assert resp.text.startswith("## Лист1") and resp.truncated is False

    # Переиндексация НЕ стирает body_text (брался из версии).
    await _reindex(db, material)
    doc = (
        await db.execute(select(SearchDocument).where(SearchDocument.object_id == material.id))
    ).scalar_one()
    assert doc.body_text and "Азу" in doc.body_text
    material.title = "Техкарта v2"
    await _reindex(db, material)
    await db.refresh(doc)
    assert doc.title == "Техкарта v2" and "Азу" in (doc.body_text or "")
