"""Шаблоны проектов (0060): «замок» RLS, доступ, копирование.

Всё под `rls_enforced`: под суперпользователем testcontainers RLS не
действует вовсе, и каждый ассерт «шаблон не виден» выродился бы в no-op.
Каждый шаг — своя сессия: область шаблона открывается один раз на сессию
(`app/db.py::set_template_scope`), как один раз на запрос в проде.

Ассерты ПАРНЫЕ там, где это возможно: «шаблона нет» рядом с «живой есть» —
иначе сломанный запрос, не возвращающий ничего, прошёл бы проверку.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.api.me_tasks import list_my_tasks
from app.api.project_templates import (
    create_project_from_template,
    create_template,
    list_templates,
    preview_project_from_template,
    save_as_template,
)
from app.api.projects import create_project, delete_project, get_project, list_projects
from app.api.stats import get_my_stats
from app.api.tasks import archive_task, create_task, set_task_recurrence, update_task
from app.config import get_settings
from app.db import set_template_scope, tenant_scoped_session
from app.deps import get_db_template_page
from app.jobs import due_soon
from app.models.attachment import TaskAttachment
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.project_template import ProjectFromTemplate, SaveAsTemplate, TemplateCreate
from app.schemas.task import TaskCreate, TaskRecurrenceBody, TaskUpdate
from app.services.personal_projects import ensure_personal_project
from app.services.project_templates import gate
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def _req(principal, method: str = "GET", **path):
    return SimpleNamespace(
        method=method,
        path_params={k: str(v) for k, v in path.items()},
        state=SimpleNamespace(principal=principal),
    )


class World:
    def __init__(self, tenant_id: uuid.UUID, slug: str) -> None:
        self.tenant_id = tenant_id
        self.author = make_principal(tenant_id, email=f"a-{slug}@t.ru", tenant_slug=slug)
        self.other = make_principal(tenant_id, email=f"c-{slug}@t.ru", tenant_slug=slug)
        self.admin = make_principal(
            tenant_id, email=f"adm-{slug}@t.ru", role="admin", tenant_slug=slug
        )
        self.worker = make_principal(tenant_id, email=f"w-{slug}@t.ru", tenant_slug=slug)
        self.assignee = make_principal(tenant_id, email=f"u-{slug}@t.ru", tenant_slug=slug)
        self.template_id: uuid.UUID
        self.template_key: str
        self.live_id: uuid.UUID
        self.tpl_task: uuid.UUID
        self.live_task: uuid.UUID


async def _world(tenant_id: uuid.UUID) -> World:
    slug = f"tpl-{tenant_id.hex[:10]}"
    w = World(tenant_id, slug)
    async with tenant_scoped_session(tenant_id) as s:
        await _register(s, w.author, org_role="office")
        await _register(s, w.other, org_role="office")
        await _register(s, w.admin)
        await _register(s, w.worker, org_role="employee")
        await _register(s, w.assignee, org_role="office")
        await gate.set_tenant_enabled(s, tenant_id, True)
        await s.commit()
        live = await create_project(ProjectCreate(name="Живой проект"), w.author, s)
        w.live_id = live.id
        t = await create_task(
            live.id,
            TaskCreate(
                title="Живая",
                assignee_ids=[w.assignee.employee_id],
                due_at=NOW + timedelta(hours=6),
            ),
            w.author,
            s,
        )
        w.live_task = t.id
    async with tenant_scoped_session(tenant_id) as s:
        tpl = await create_template(
            TemplateCreate(name="Открытие точки", anchor_on=date(2026, 9, 1)), w.author, s
        )
        w.template_id, w.template_key = tpl.id, tpl.key
    async with tenant_scoped_session(tenant_id) as s:
        db = await get_db_template_page(
            _req(w.author, "POST", project_id=w.template_id), s
        )
        t = await create_task(
            w.template_id,
            TaskCreate(
                title="Шаблонная",
                assignee_ids=[w.assignee.employee_id],
                # Срок в окне due_soon: джоба под bypass обязана его НЕ видеть.
                due_at=NOW + timedelta(hours=6),
            ),
            w.author,
            db,
        )
        w.tpl_task = t.id
    return w


# ─── Шаблон не виден ─────────────────────────────────────────────────────────


async def test_template_hidden_from_lists_me_tasks_and_jobs(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        for p in (w.author, w.admin):
            ids = {x.id for x in await list_projects(include_archived=True, principal=p, db=s)}
            assert w.live_id in ids and w.template_id not in ids
        mine = await list_my_tasks(
            done=None, status_=None, due_window=None, include_archived=True,
            include_personal=True, principal=w.assignee, db=s,
        )
        got = {t.id for t in mine}
        assert w.live_task in got and w.tpl_task not in got
        # Прямой вызов ручки — без зависимости страницы шаблона: 404.
        with pytest.raises(HTTPException) as exc:
            await get_project(w.template_id, w.author, s)
        assert exc.value.status_code == 404
    # Cron под bypass: замок действует и там.
    async with tenant_scoped_session(None, bypass_rls=True) as s:
        ids = {row[0].id for row in (await s.execute(due_soon.scan_stmt(NOW))).all()}
        assert w.live_task in ids and w.tpl_task not in ids
        n = (await s.execute(text("SELECT count(*) FROM projects WHERE is_template"))).scalar()
        assert n == 0
    async with tenant_scoped_session(None, bypass_rls=True, template_scope="all") as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM projects WHERE is_template AND tenant_id = :t"),
                {"t": w.tenant_id},
            )
        ).scalar()
        assert n == 1


async def test_scope_all_does_not_cross_tenants_and_pool_is_reset(rls_enforced):
    w = await _world(uuid.uuid4())
    other_tenant = uuid.uuid4()
    async with tenant_scoped_session(other_tenant, template_scope="all") as s:
        n = (await s.execute(text("SELECT count(*) FROM projects WHERE is_template"))).scalar()
        assert n == 0
    # Грязное соединение: 'all' на уровне СЕССИИ Postgres, потом commit —
    # листенер обязан поставить пустую область в следующей транзакции.
    async with tenant_scoped_session(w.tenant_id) as s:
        await s.execute(text("SELECT set_config('app.template_scope', 'all', false)"))
        await s.commit()
        n = (await s.execute(text("SELECT count(*) FROM projects WHERE is_template"))).scalar()
        assert n == 0


async def test_live_project_may_reuse_template_key(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        p = await create_project(
            ProjectCreate(name="Тёзка", key=w.template_key), w.author, s
        )
        assert p.key == w.template_key
    # Автоподбор ключа не спотыкается о невидимый шаблон, личное пространство
    # новому сотруднику создаётся.
    newbie = make_principal(w.tenant_id, email=f"n-{w.tenant_id.hex[:6]}@t.ru",
                            tenant_slug=f"tpl-{w.tenant_id.hex[:10]}")
    async with tenant_scoped_session(w.tenant_id) as s:
        await _register(s, newbie, org_role="office")
        await s.commit()
        assert await ensure_personal_project(s, newbie) is not None


async def test_lock_rejects_bad_writes(rls_enforced):
    w = await _world(uuid.uuid4())
    base = {
        "tid": w.tenant_id, "pid": w.template_id, "uid": w.author.employee_id,
    }
    sql = (
        "INSERT INTO tasks (id, tenant_id, project_id, title, created_by, position, seq, "
        "is_template) VALUES (gen_random_uuid(), :tid, :pid, 'x', :uid, 1, 999, :tpl)"
    )
    # Без открытой области строка шаблона не проходит политику.
    async with tenant_scoped_session(w.tenant_id) as s:
        with pytest.raises(DBAPIError):
            await s.execute(text(sql), {**base, "tpl": True})
    # Неверный флаг — триггер, даже с открытой областью.
    async with tenant_scoped_session(w.tenant_id, template_scope=str(w.template_id)) as s:
        with pytest.raises(DBAPIError):
            await s.execute(text(sql), {**base, "tpl": False})
    # Перенос задачи шаблона в живой проект сырым UPDATE — триггер.
    async with tenant_scoped_session(w.tenant_id, template_scope=str(w.template_id)) as s:
        with pytest.raises(DBAPIError):
            await s.execute(
                text("UPDATE tasks SET project_id = :live WHERE id = :t"),
                {"live": w.live_id, "t": w.tpl_task},
            )
    # Шаблон нельзя превратить в проект.
    async with tenant_scoped_session(w.tenant_id, template_scope=str(w.template_id)) as s:
        with pytest.raises(DBAPIError):
            await s.execute(
                text("UPDATE projects SET is_template = false WHERE id = :p"),
                {"p": w.template_id},
            )


async def test_scope_cannot_switch_or_open_in_savepoint(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        await set_template_scope(s, str(w.template_id))
        with pytest.raises(RuntimeError):
            await set_template_scope(s, str(uuid.uuid4()))
    async with tenant_scoped_session(w.tenant_id) as s, s.begin_nested():
        with pytest.raises(RuntimeError):
            await set_template_scope(s, "all")


async def test_template_side_effects_are_silent(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id, template_scope=str(w.template_id)) as s:
        # Назначение в шаблоне: ни уведомления, ни членства в составе.
        n = (
            await s.execute(
                select(Notification).where(Notification.employee_id == w.assignee.employee_id)
            )
        ).scalars().all()
        assert all(f"/projects/{w.template_id}" not in (x.url or "") for x in n)
        roster = set(
            (
                await s.execute(
                    select(ProjectMember.employee_id).where(
                        ProjectMember.project_id == w.template_id
                    )
                )
            ).scalars()
        )
        # Автор — тоже не в составе: состав шаблона — будущие участники.
        assert roster == set()
        task = await s.get(Task, w.tpl_task)
        assert task is not None and task.is_template


# ─── Доступ ──────────────────────────────────────────────────────────────────


async def test_access_matrix(rls_enforced):
    w = await _world(uuid.uuid4())
    # Не-автор с правом создавать проекты — видит, но не правит.
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.other, project_id=w.template_id), s)
        p = await get_project(w.template_id, w.other, db)
        assert p.is_template and not p.can_edit
    async with tenant_scoped_session(w.tenant_id) as s:
        with pytest.raises(HTTPException) as exc:
            await get_db_template_page(_req(w.other, "PATCH", task_id=w.tpl_task), s)
        assert exc.value.status_code == 403
    # Автор и admin правят.
    for who in (w.author, w.admin):
        async with tenant_scoped_session(w.tenant_id) as s:
            db = await get_db_template_page(_req(who, project_id=w.template_id), s)
            assert (await get_project(w.template_id, who, db)).can_edit
    # Линейный сотрудник — шаблона «не существует».
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.worker, project_id=w.template_id), s)
        with pytest.raises(HTTPException) as exc:
            await get_project(w.template_id, w.worker, db)
        assert exc.value.status_code == 404
    # Выключенный модуль — тоже 404, данные на месте.
    async with tenant_scoped_session(w.tenant_id) as s:
        await gate.set_tenant_enabled(s, w.tenant_id, False)
        await s.commit()
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.author, project_id=w.template_id), s)
        with pytest.raises(HTTPException) as exc:
            await get_project(w.template_id, w.author, db)
        assert exc.value.status_code == 404


async def test_done_and_comments_refused_in_template(rls_enforced):
    from app.api.comments import create_comment
    from app.schemas.comment import CommentCreate

    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.author, "PATCH", task_id=w.tpl_task), s)
        with pytest.raises(HTTPException) as exc:
            await update_task(w.tpl_task, TaskUpdate(done=True), w.author, db)
        assert exc.value.status_code == 409
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.author, "POST", task_id=w.tpl_task), s)
        with pytest.raises(HTTPException) as exc:
            await create_comment(w.tpl_task, CommentCreate(body="заметка"), w.author, db)
        assert exc.value.status_code == 409


async def test_library(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        items = await list_templates(w.other, s)
        assert [i.id for i in items] == [w.template_id]
        assert items[0].task_count == 1 and not items[0].can_edit
    async with tenant_scoped_session(w.tenant_id) as s:
        with pytest.raises(HTTPException) as exc:
            await list_templates(w.worker, s)
        assert exc.value.status_code == 403


# ─── Копирование ─────────────────────────────────────────────────────────────


async def test_project_from_template_copies_and_notifies_once(rls_enforced):
    w = await _world(uuid.uuid4())
    start = date.today() + timedelta(days=10)
    async with tenant_scoped_session(w.tenant_id) as s:
        preview = await preview_project_from_template(w.template_id, start, w.other, s)
        assert preview.tasks == 1 and preview.notify_people == 1
    async with tenant_scoped_session(w.tenant_id) as s:
        out = await create_project_from_template(
            w.template_id,
            ProjectFromTemplate(name="Невский 10", start_on=start),
            w.other,
            s,
        )
    new_id = out.project.id
    assert out.report.tasks == 1 and out.report.notified == 1
    async with tenant_scoped_session(w.tenant_id) as s:
        ids = {x.id for x in await list_projects(include_archived=False, principal=w.other, db=s)}
        assert new_id in ids and w.template_id not in ids
        tasks = (await s.execute(select(Task).where(Task.project_id == new_id))).scalars().all()
        assert [t.seq for t in tasks] == [1]
        t = tasks[0]
        assert not t.is_template and t.template_copy and t.created_by == w.other.employee_id
        # Сдвиг: исходный срок −(anchor 01.09) + старт.
        roster = dict(
            (
                await s.execute(
                    select(ProjectMember.employee_id, ProjectMember.role).where(
                        ProjectMember.project_id == new_id
                    )
                )
            ).all()
        )
        assert roster[w.other.employee_id] == "owner"
        assert roster[w.assignee.employee_id] == "viewer"
        # Автор шаблона в новый проект сам не попадает.
        assert w.author.employee_id not in roster
        notes = (
            await s.execute(
                select(Notification).where(Notification.employee_id == w.assignee.employee_id)
            )
        ).scalars().all()
        summary = [x for x in notes if (x.url or "").startswith(f"/projects/{new_id}")]
        assert len(summary) == 1 and summary[0].kind == "task.assigned_to_me"
        # «Создано» у создавшего проект не выросло на копии.
        stats = await get_my_stats(w.other, s)
        assert stats.created_7 == 0
        project = await s.get(Project, new_id)
        assert project is not None and project.created_from_template_id == w.template_id


async def test_start_in_past_is_allowed_and_counted(rls_enforced):
    # Решение владельца 21.09: задним числом можно. Предпросмотр обязан
    # назвать цену — сколько задач сразу окажутся просроченными.
    w = await _world(uuid.uuid4())
    start = date.today() - timedelta(days=30)
    async with tenant_scoped_session(w.tenant_id) as s:
        preview = await preview_project_from_template(w.template_id, start, w.other, s)
        assert preview.overdue_after_shift == 1
    async with tenant_scoped_session(w.tenant_id) as s:
        out = await create_project_from_template(
            w.template_id, ProjectFromTemplate(name="Задним числом", start_on=start), w.other, s
        )
        assert out.report.tasks == 1


async def test_save_as_template_rules(rls_enforced, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachments_root", tmp_path)
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        arch = await create_task(w.live_id, TaskCreate(title="Архивный родитель"), w.author, s)
    async with tenant_scoped_session(w.tenant_id) as s:
        await create_task(
            w.live_id, TaskCreate(title="Сирота", parent_task_id=arch.id), w.author, s
        )
    async with tenant_scoped_session(w.tenant_id) as s:
        await archive_task(arch.id, w.author, s)
    async with tenant_scoped_session(w.tenant_id) as s:
        await set_task_recurrence(w.live_task, TaskRecurrenceBody(freq="week"), w.author, s)
    # Вложение на диске + строка.
    key = f"{w.tenant_id}/{w.live_task}/abc-plan.pdf"
    (tmp_path / key).parent.mkdir(parents=True)
    (tmp_path / key).write_bytes(b"%PDF-1.4 test")
    async with tenant_scoped_session(w.tenant_id) as s:
        s.add(
            TaskAttachment(
                tenant_id=w.tenant_id, task_id=w.live_task, uploaded_by=w.assignee.employee_id,
                filename="План.pdf", mime="application/pdf", size_bytes=13, storage_key=key,
            )
        )
        await s.commit()
    async with tenant_scoped_session(w.tenant_id) as s:
        tpl = await save_as_template(
            w.live_id, SaveAsTemplate(name="Из живого"), w.author, s
        )
    async with tenant_scoped_session(w.tenant_id, template_scope=str(tpl.id)) as s:
        tasks = (await s.execute(select(Task).where(Task.project_id == tpl.id))).scalars().all()
        # Архивный родитель и его подзадача-сирота не скопированы.
        assert [t.title for t in tasks] == ["Живая"]
        assert tasks[0].is_template and not tasks[0].template_copy
        roster = set(
            (
                await s.execute(
                    select(ProjectMember.employee_id).where(ProjectMember.project_id == tpl.id)
                )
            ).scalars()
        )
        # Сохраняющий в состав не копируется (решение №13).
        assert w.author.employee_id not in roster
        att = (
            await s.execute(select(TaskAttachment).where(TaskAttachment.task_id == tasks[0].id))
        ).scalar_one()
        assert att.uploaded_by == w.author.employee_id
        assert os.stat(tmp_path / att.storage_key).st_ino == os.stat(tmp_path / key).st_ino
        rule = (
            await s.execute(text("SELECT anchor FROM task_recurrences WHERE task_id = :t"),
                            {"t": tasks[0].id})
        ).scalar_one()
        assert rule is not None
    # Удаление шаблона не трогает файл живого проекта.
    async with tenant_scoped_session(w.tenant_id) as s:
        db = await get_db_template_page(_req(w.author, "DELETE", project_id=tpl.id), s)
        await delete_project(tpl.id, tpl.key, w.author, db)
    assert (tmp_path / key).read_bytes() == b"%PDF-1.4 test"


async def test_admin_cannot_template_someones_personal(rls_enforced):
    w = await _world(uuid.uuid4())
    async with tenant_scoped_session(w.tenant_id) as s:
        personal = await ensure_personal_project(s, w.assignee)
        await s.commit()
    assert personal is not None
    async with tenant_scoped_session(w.tenant_id) as s:
        with pytest.raises(HTTPException) as exc:
            await save_as_template(personal, SaveAsTemplate(name="Чужое"), w.admin, s)
        assert exc.value.status_code == 409
