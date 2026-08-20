"""Ассистент, волна 1: границы прав инструментов и жизненный цикл плана.

Проверяем не «ассистент отвечает», а ровно то, что делает его безопасным:
инструмент не показывает чужой проект, отказ приходит данными с именами
тех, кто вправе, создание не выполняется без подтверждения, план исполняется
один раз и перепроверяет права в момент нажатия.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import create_project
from app.api.tasks import create_task
from app.models.ai import AiPlan
from app.models.project import ProjectMember
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.services.assistant import plans as plan_service
from app.services.assistant.context import Ambiguous, NotFound, ToolContext
from app.services.assistant.tools import (
    CreateTaskArgs,
    SearchTasksArgs,
    TaskRefArgs,
    UpdateTaskArgs,
    parse_due,
    t_create_task,
    t_search_tasks,
    t_update_task,
)
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _add_member, _register

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    from app.services import notify_batch

    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


def _ctx(db: AsyncSession, principal) -> ToolContext:
    """Учебного профиля нет намеренно: ассистент обязан работать у
    пользователя-только-трекера (из-за этого и заведён employee_id)."""
    return ToolContext(db=db, principal=principal, profile=None)


async def _seed(db: AsyncSession, tenant_id: uuid.UUID, slug: str):
    owner = make_principal(
        tenant_id, email=f"owner-{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, owner)
    project = await create_project(ProjectCreate(name=f"Проект {slug}"), owner, db)
    return owner, project


# ─── Границы видимости ──────────────────────────────────────────────────────


async def test_search_tasks_hides_foreign_project(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "asrch")
    await create_task(project.id, TaskCreate(title="Секретная задача"), owner, db)

    stranger = make_principal(
        tenant_id, email="stranger@t.ru", role="member", tenant_slug="asrch"
    )
    await _register(db, stranger)

    mine = await t_search_tasks(_ctx(db, owner), SearchTasksArgs())
    assert any(t["title"] == "Секретная задача" for t in mine["tasks"])

    theirs = await t_search_tasks(_ctx(db, stranger), SearchTasksArgs())
    assert not any(t["title"] == "Секретная задача" for t in theirs["tasks"]), (
        "ассистент показал задачу из чужого проекта"
    )


async def test_admin_sees_whole_tenant(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "aadm")
    await create_task(project.id, TaskCreate(title="Задача админа"), owner, db)
    admin = make_principal(
        tenant_id, email="admin@t.ru", role="admin", tenant_slug="aadm"
    )
    await _register(db, admin)

    # Скоуп по своему проекту: endpoint-функции коммитят, и задачи соседних
    # тестов живут в той же БД.
    found = await t_search_tasks(
        _ctx(db, admin), SearchTasksArgs(project=project.name)
    )
    assert [t["title"] for t in found["tasks"]] == ["Задача админа"]


# ─── Отказ по правам — данными, а не исключением ────────────────────────────


async def test_viewer_gets_denied_with_who_can(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "aden")
    viewer = make_principal(
        tenant_id, email="viewer@t.ru", role="member", tenant_slug="aden"
    )
    await _register(db, viewer)
    await _add_member(db, tenant_id, project.id, viewer, "viewer")

    result = await t_create_task(
        _ctx(db, viewer),
        CreateTaskArgs(project=project.name, title="Нельзя"),
    )
    assert result["denied"] is True
    assert "наблюдател" in result["reason"]
    # Кого просить — обязательная часть отказа: макет рисует «Попросить …».
    assert any(w["role"] == "владелец" for w in result["who_can"])
    assert "__plan__" not in result


# ─── Порог подтверждения ────────────────────────────────────────────────────


async def test_create_task_only_proposes(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "acre")

    result = await t_create_task(
        _ctx(db, owner),
        CreateTaskArgs(
            project=project.name,
            title="Заменить экраны в Галерее",
            due_at="2026-08-22",
            priority="urgent",
        ),
    )
    proposal = result["__plan__"]
    assert proposal["tool"] == "create_task"
    assert proposal["scope"] == "создание задачи · 1 объект"
    labels = [f["label"] for f in proposal["preview"]["fields"]]
    assert labels == ["Проект", "Заголовок", "Срок", "Приоритет"]

    # Главное: задачи ещё НЕТ.
    count = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all()
    assert count == []


async def test_update_single_task_is_immediate(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "aupd")
    task = await create_task(project.id, TaskCreate(title="Правка"), owner, db)

    result = await t_update_task(
        _ctx(db, owner),
        UpdateTaskArgs(task=f"{project.key}-{task.seq}", status="done", priority="high"),
    )
    assert result["done"] is True
    assert result["status"] == "Готово"

    fresh = await db.get(Task, task.id)
    await db.refresh(fresh)
    assert fresh.status == "done"


# ─── Жизненный цикл плана ───────────────────────────────────────────────────


async def _make_plan(db: AsyncSession, tenant_id, owner, project) -> AiPlan:
    from app.models.ai import AiConversation

    conversation = AiConversation(
        tenant_id=tenant_id,
        employee_id=owner.employee_id,
        profile_id=None,
        title="Тест",
    )
    db.add(conversation)
    await db.flush()
    proposal = (
        await t_create_task(
            _ctx(db, owner),
            CreateTaskArgs(project=project.name, title="Из плана", priority="urgent"),
        )
    )["__plan__"]
    plan = plan_service.create(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        employee_id=owner.employee_id,
        proposal=proposal,
    )
    await db.commit()
    return plan


async def test_plan_executes_exactly_once(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "aex1")
    plan = await _make_plan(db, tenant_id, owner, project)

    done = await plan_service.execute(db, plan, owner)
    assert done.status == "done"
    assert done.result["text"].startswith("Создана ")

    tasks = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].priority == "urgent"

    # Повторное нажатие «Выполнить» второй задачи не создаёт.
    with pytest.raises(plan_service.PlanError):
        await plan_service.execute(db, done, owner)
    tasks_after = (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all()
    assert len(tasks_after) == 1


async def test_expired_plan_is_refused(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "aexp")
    plan = await _make_plan(db, tenant_id, owner, project)
    plan.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    with pytest.raises(plan_service.PlanError) as exc:
        await plan_service.execute(db, plan, owner)
    assert "получас" in str(exc.value)
    assert (await db.get(AiPlan, plan.id)).status == "failed"
    assert (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all() == []


async def test_rights_rechecked_at_execution(db: AsyncSession, tenant_id: uuid.UUID):
    """Между планом и «Выполнить» сотрудника вывели из проекта."""
    owner, project = await _seed(db, tenant_id, "arec")
    editor = make_principal(
        tenant_id, email="editor@t.ru", role="member", tenant_slug="arec"
    )
    await _register(db, editor)
    await _add_member(db, tenant_id, project.id, editor, "editor")

    plan = await _make_plan(db, tenant_id, editor, project)

    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.employee_id == editor.employee_id,
        )
    )
    await db.commit()

    with pytest.raises(plan_service.PlanError):
        await plan_service.execute(db, plan, editor)
    assert (
        await db.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all() == []


async def test_foreign_plan_is_invisible(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "afor")
    plan = await _make_plan(db, tenant_id, owner, project)
    other = make_principal(
        tenant_id, email="other@t.ru", role="member", tenant_slug="afor"
    )
    await _register(db, other)

    with pytest.raises(HTTPException) as exc:
        await plan_service.load_for_actor(db, plan.id, other)
    assert exc.value.status_code == 404


# ─── Резолверы ──────────────────────────────────────────────────────────────


async def test_task_key_resolution_and_errors(db: AsyncSession, tenant_id: uuid.UUID):
    owner, project = await _seed(db, tenant_id, "akey")
    task = await create_task(project.id, TaskCreate(title="Ключевая"), owner, db)
    from app.services.assistant.tools import t_get_task

    found = await t_get_task(_ctx(db, owner), TaskRefArgs(task=f"{project.key}-{task.seq}"))
    assert found["title"] == "Ключевая"

    # Голый номер не принимаем: seq уникален лишь внутри проекта.
    with pytest.raises(NotFound):
        await t_get_task(_ctx(db, owner), TaskRefArgs(task="133"))


async def test_ambiguous_person_asks_back(db: AsyncSession, tenant_id: uuid.UUID):
    from signaris_auth.shadow import upsert_shadow_user

    owner, project = await _seed(db, tenant_id, "aamb")
    for i, name in enumerate(("Дмитрий Фёдоров", "Дмитрий Орлов")):
        twin = make_principal(
            tenant_id, email=f"dmitry{i}@t.ru", full_name=name, tenant_slug="aamb"
        )
        await upsert_shadow_user(db, twin, table="shadow_users")
    await db.flush()

    with pytest.raises(Ambiguous) as exc:
        await t_create_task(
            _ctx(db, owner),
            CreateTaskArgs(project=project.name, title="Кому?", assignees=["Дмитрий"]),
        )
    assert len(exc.value.candidates) == 2


def test_due_date_lands_on_the_same_day():
    """Полночь UTC уехала бы на предыдущий день в карточке задачи."""
    due = parse_due("2026-08-22")
    assert due is not None
    from zoneinfo import ZoneInfo

    assert due.astimezone(ZoneInfo("Europe/Moscow")).date().isoformat() == "2026-08-22"
    # Ровно то, что кладёт TaskDetailDrawer: локальный полдень.
    assert due.astimezone(ZoneInfo("Europe/Moscow")).hour == 12


# ─── Журнал показывает ЖИВОЕ состояние плана ────────────────────────────────


async def test_journal_shows_live_plan_state(db: AsyncSession, tenant_id: uuid.UUID):
    """Регресс staging 20.08: план хранился в сообщении СНИМКОМ, поэтому после
    «Выполнить» карточка навсегда оставалась «проверьте перед выполнением» —
    задача уже создана, а интерфейс предлагал создать её снова."""
    from app.api.assistant import conversation_messages
    from app.models.ai import AiConversation, AiMessage

    owner, project = await _seed(db, tenant_id, "alive")
    conversation = AiConversation(
        tenant_id=tenant_id,
        employee_id=owner.employee_id,
        profile_id=None,
        title="Живой план",
    )
    db.add(conversation)
    await db.flush()
    proposal = (
        await t_create_task(
            _ctx(db, owner),
            CreateTaskArgs(project=project.name, title="Живая карточка"),
        )
    )["__plan__"]
    plan = plan_service.create(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        employee_id=owner.employee_id,
        proposal=proposal,
    )
    await db.flush()
    db.add(
        AiMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            kind="action",
            content="",
            data={"plan_id": str(plan.id)},
        )
    )
    await db.commit()

    before = await conversation_messages(conversation.id, owner, db)
    assert before[0].data is not None
    assert before[0].data["plan"]["status"] == "pending"

    await plan_service.execute(db, plan, owner)

    after = await conversation_messages(conversation.id, owner, db)
    assert after[0].data is not None
    assert after[0].data["plan"]["status"] == "done"
    assert after[0].data["plan"]["result"]["text"].startswith("Создана ")


async def test_action_turn_leaves_trace_in_history(db: AsyncSession, tenant_id: uuid.UUID):
    """Регресс staging 20.08: карточка плана рисуется без прозы, ответ уходил
    в БД пустым, и в истории просьба «создай задачу» выглядела неотвеченной —
    на следующий (совсем другой) вопрос модель предлагала создать ту же
    задачу заново. Пустых ассистентских реплик в истории быть не должно."""
    from app.api.assistant import _history
    from app.models.ai import AiConversation, AiMessage

    owner, project = await _seed(db, tenant_id, "atrace")
    conversation = AiConversation(
        tenant_id=tenant_id,
        employee_id=owner.employee_id,
        profile_id=None,
        title="След",
    )
    db.add(conversation)
    await db.flush()
    proposal = (
        await t_create_task(
            _ctx(db, owner), CreateTaskArgs(project=project.name, title="Со следом")
        )
    )["__plan__"]
    plan = plan_service.create(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        employee_id=owner.employee_id,
        proposal=proposal,
    )
    await db.flush()
    db.add(
        AiMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            kind="answer",
            content="Создай задачу «Со следом»",
        )
    )
    db.add(
        AiMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            kind="action",
            content="",
            data={"plan_id": str(plan.id)},
        )
    )
    await db.commit()

    history = await _history(db, conversation.id)
    assert [m.role for m in history] == ["user", "assistant"]
    assert "ждёт подтверждения" in history[1].content

    await plan_service.execute(db, plan, owner)
    after = await _history(db, conversation.id)
    assert "Действие выполнено" in after[1].content
