"""Архивный проект больше не принимает НОВЫЕ задачи (28.08).

До этой правки архивность не проверяла ни одна ручка трекера — прятал создание
только клиент. Живой путь мимо клиента был у ассистента: он резолвил проект по
имени и заводил задачу, которая тут же выпадала из поиска
(`api/search.py` фильтрует архивные проекты) и из всех списков. С точки зрения
человека работа исчезала.

Гейт стоит ТОЛЬКО на создании. Правка существующей задачи в архивном проекте
разрешена сознательно, и на это здесь отдельный тест: без него следующий агент
«дочинит» недостающую проверку и сломает массовые правки ассистента.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import archive_project, create_project, unarchive_project
from app.api.tasks import create_task, update_task
from app.api.tasks_import import import_tasks
from app.config import get_settings
from app.models.project import Project
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.assistant.context import ToolContext, resolve_task
from app.services.assistant.tools import (
    CreateTaskArgs,
    t_create_task,
    t_list_projects,
)
from app.services.feedback import find_feedback_project
from app.services.onboarding import create_guide_task
from app.services.personal_projects import ensure_personal_project
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


class _NoArgs(BaseModel):
    """`t_list_projects` аргументов не берёт, а pydantic v2 не даёт
    инстанцировать сам `BaseModel`."""


def _ctx(db: AsyncSession, principal) -> ToolContext:
    return ToolContext(db=db, principal=principal, profile=None)


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="tasks.csv")


async def _archived(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """Владелец, живой проект и его архивный сосед."""
    owner = make_principal(
        tenant_id, email=f"own-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner, org_role="office")
    alive = await create_project(ProjectCreate(name=f"Живой {slug}"), owner, db)
    dead = await create_project(ProjectCreate(name=f"Архивный {slug}"), owner, db)
    await db.commit()
    await archive_project(dead.id, owner, db)
    return owner, alive, dead


# ─── Создание ───────────────────────────────────────────────────────────────


async def test_create_is_refused_in_archive_and_still_works_next_door(
    db: AsyncSession, tenant_id: uuid.UUID
):
    owner, alive, dead = await _archived(db, tenant_id, "ar1")

    with pytest.raises(HTTPException) as exc:
        await create_task(dead.id, TaskCreate(title="Потеряшка"), owner, db)
    assert exc.value.status_code == 409
    assert "архив" in str(exc.value.detail).lower()

    # Регресс-страховка: гейт не должен задеть обычное создание.
    created = await create_task(alive.id, TaskCreate(title="Обычная"), owner, db)
    assert created.project_id == alive.id


async def test_import_refuses_whole_file_without_writing_a_row(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Транзакция одна и commit в конце — отказ на первой строке чист."""
    owner, _alive, dead = await _archived(db, tenant_id, "ar2")
    csv = "title;priority\nПервая;высокий\nВторая;средний\n"

    for dry_run in (True, False):
        with pytest.raises(HTTPException) as exc:
            await import_tasks(dead.id, _upload(csv), dry_run, owner, db)
        assert exc.value.status_code == 409
        await db.rollback()

    left = (
        await db.execute(select(Task.id).where(Task.project_id == dead.id))
    ).scalars().all()
    assert list(left) == []


async def test_editing_an_existing_task_in_archive_still_works(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """РЕШЕНИЕ, а не забытый случай: задача уже есть и открывается по ссылке,
    а запрет сломал бы массовые правки ассистента посреди плана."""
    owner, _alive, dead = await _archived(db, tenant_id, "ar3")
    # Задача заведена ДО архивации — обычный жизненный путь.
    await unarchive_project(dead.id, owner, db)
    task = await create_task(dead.id, TaskCreate(title="Старая"), owner, db)
    await db.commit()
    await archive_project(dead.id, owner, db)

    updated = await update_task(
        task.id, TaskUpdate(title="Старая, но поправленная"), owner, db
    )
    assert updated.title == "Старая, но поправленная"


async def test_unarchiving_opens_creation_back(db: AsyncSession, tenant_id: uuid.UUID):
    owner, _alive, dead = await _archived(db, tenant_id, "ar4")
    await unarchive_project(dead.id, owner, db)

    created = await create_task(dead.id, TaskCreate(title="Снова можно"), owner, db)
    assert created.project_id == dead.id


# ─── Ассистент ──────────────────────────────────────────────────────────────


async def test_assistant_hides_archived_from_the_catalogue_but_still_reads_it(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Фильтр — точечно в `t_list_projects`, а не в `visible_projects_stmt`.

    Общая выборка кормит `resolve_task` и `resolve_project`, а они обязаны
    находить архивный проект по ключу и по имени: прямая ссылка на него
    открывается, правка задач разрешена, и «покажи задачи в PKNG» должно
    отвечать правду. Что из ЛИЧНЫХ списков архивные ушли — отдельное правило и
    отдельный файл (`test_archived_projects_hidden.py`).
    """
    owner, alive, dead = await _archived(db, tenant_id, "ar5")
    await unarchive_project(dead.id, owner, db)
    task = await create_task(dead.id, TaskCreate(title="В архиве"), owner, db)
    await db.commit()
    await archive_project(dead.id, owner, db)

    listed = await t_list_projects(_ctx(db, owner), _NoArgs())
    names = [p["name"] for p in listed["projects"]]
    assert alive.name in names
    assert dead.name not in names, "архивный проект попал в каталог ассистента"

    # Чтение осталось: задачу по её ключу ассистент по-прежнему находит.
    found = await resolve_task(_ctx(db, owner), f"{dead.key}-{task.seq}")
    assert found.id == task.id


async def test_assistant_refuses_to_plan_creation_in_archive(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Отказ обязан быть на ПОСТРОЕНИИ плана: иначе человек нажал бы
    «Выполнить» и получил ошибку от ручки."""
    owner, _alive, dead = await _archived(db, tenant_id, "ar6")

    result = await t_create_task(
        _ctx(db, owner), CreateTaskArgs(project=dead.name, title="Не надо")
    )
    assert result["denied"] is True
    assert "архив" in result["reason"].lower()
    # Владелец прав не выдаёт — советовать «попросите его» здесь вредно.
    assert result["who_can"] == []
    assert "__plan__" not in result


# ─── Соседние пути, которые гейт задевать не должен ─────────────────────────


async def test_feedback_reads_archived_project_as_not_configured(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Иначе сотрудник, пишущий в поддержку, получил бы 409 про проект,
    которого он не выбирал и не видел."""
    owner = make_principal(
        tenant_id, email="own-ar7@t.ru", role="member", tenant_slug="ar7"
    )
    await _register(db, owner, org_role="office")
    key = get_settings().feedback_project_key
    project = await create_project(ProjectCreate(name=f"Приём {key}"), owner, db)
    # Ключ приёма задаётся настройкой, а `create_project` считает его из имени.
    project_row = await db.get(Project, project.id)
    assert project_row is not None
    project_row.key = key
    await db.commit()

    assert (await find_feedback_project(db, tenant_id)).id == project.id

    await archive_project(project.id, owner, db)
    with pytest.raises(HTTPException) as exc:
        await find_feedback_project(db, tenant_id)
    assert exc.value.status_code == 503
    assert "не настроена" in str(exc.value.detail)


async def test_guide_task_for_a_newcomer_is_unaffected(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Личный проект архивировать нельзя, поэтому гейт до него не дотягивается —
    а падение здесь роняло бы `GET /api/me`, то есть вход в приложение."""
    person = make_principal(
        tenant_id, email="new-ar8@t.ru", role="member", tenant_slug="ar8"
    )
    await _register(db, person)
    personal_id = await ensure_personal_project(db, person)
    await db.commit()
    assert personal_id is not None

    task = await create_guide_task(db, principal=person, project_id=personal_id)
    assert task is not None
