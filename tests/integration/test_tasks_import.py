"""Импорт задач из CSV: общий путь с create_task (seq без дыр), dry-run без
записи, разбор cp1251/«;», построчные предупреждения, справочники по имени."""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.labels import create_label
from app.api.projects import create_project
from app.api.sections import create_section
from app.api.stages import list_project_stages
from app.api.tasks import list_tasks
from app.api.tasks_import import import_tasks
from app.schemas.label import LabelCreate
from app.schemas.project import ProjectCreate
from app.schemas.section import SectionCreate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


def _upload(text: str, encoding: str = "utf-8") -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode(encoding)), filename="tasks.csv")


async def _list(db, project_id, owner):
    return await list_tasks(
        project_id,
        include_archived=False,
        status_=None,
        assignee_id=None,
        section_id=None,
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


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    project = await create_project(ProjectCreate(name=f"Import {slug}"), owner, db)
    return owner, project


async def test_import_creates_tasks_with_refs_and_warnings(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "imp1")
    await create_section(project.id, SectionCreate(name="Плейлисты"), owner, db)
    await create_label(project.id, LabelCreate(name="Контент", color="#00B4A8"), owner, db)
    stage_rows = await list_project_stages(project.id, principal=owner, db=db)
    stages = {s.system_status: s for s in stage_rows}

    csv_text = (
        "title;description;assignee_email;due;priority;section;stage;labels\n"
        "Согласовать сетку;Осенний плейлист;owner-imp1@t.ru;14.08.2026;высокий;"
        "Плейлисты;В работе;Контент\n"
        "Перезалить ролики;;nobody@t.ru;2026-09-05;urgent;Нет такой;Готово;Нет метки|Контент\n"
        ";пустой заголовок;;;;;;\n"
    )
    report = await import_tasks(
        project.id, file=_upload(csv_text, "cp1251"), dry_run=False, principal=owner, db=db
    )
    assert report.created == 2 and report.skipped == 1 and not report.dry_run
    joined = "\n".join(report.errors)
    assert "исполнитель nobody@t.ru не найден" in joined
    assert "секция «Нет такой» не найдена" in joined
    assert "метка «Нет метки» не найдена" in joined
    assert "Строка 4: пустой title" in joined

    tasks = {t.title: t for t in await _list(db, project.id, owner)}
    first = tasks["Согласовать сетку"]
    assert first.priority == "high"
    assert first.due_at is not None and first.due_at.day == 14
    assert first.stage_id == stages["in_progress"].id and first.status == "in_progress"
    assert [a.employee_id for a in first.assignees] == [owner.employee_id]
    second = tasks["Перезалить ролики"]
    assert second.stage_id == stages["done"].id and second.status == "done"
    assert second.assignees == []
    # Номера без дыр: 1, 2 (через общий путь allocate_task_seq)
    assert sorted(t.seq for t in tasks.values()) == [1, 2]


async def test_import_dry_run_writes_nothing(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "imp2")
    report = await import_tasks(
        project.id,
        file=_upload("title,due\nПроверка,21.08.2026\n"),
        dry_run=True,
        principal=owner,
        db=db,
    )
    assert report.created == 1 and report.dry_run
    assert await _list(db, project.id, owner) == []


async def test_import_requires_title_column(db: AsyncSession, tenant_id: uuid.UUID):
    from fastapi import HTTPException

    owner, project = await _seed(db, tenant_id, "imp3")
    with pytest.raises(HTTPException) as exc:
        await import_tasks(
            project.id, file=_upload("name;due\nX;\n"), dry_run=False, principal=owner, db=db
        )
    assert exc.value.status_code == 422
