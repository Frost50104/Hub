"""«Мои задачи» после слияния с личным пространством (16.09).

Экран `/my` стал единственным входом: личные задачи идут вперемешку с
рабочими, страница личного проекта на него редиректит. Отсюда два изменения
контракта `/me/tasks`, которые и проверяются здесь:

1. `include_personal` по умолчанию `True`;
2. «моё» = назначено мне ИЛИ лежит в моём личном — вторая ветка нужна для
   задачи без исполнителей, которую раньше показывала ручка проекта.

Плюс новая ручка «Назначенные мной», поглотившая секцию «Я поставил».
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.me_delegate import DelegateCreate, delegate_personal_task, list_delegated
from app.api.me_tasks import list_assigned_by_me, list_my_tasks
from app.api.projects import create_project, remove_member
from app.api.tasks import create_task, get_task, update_task
from app.models.project import ProjectMember
from app.models.task import Task, TaskWatcher
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.personal_projects import ensure_personal_project
from tests.integration.conftest import make_principal, seed_stages
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _member(db: AsyncSession, tenant_id: uuid.UUID, slug: str) -> Principal:
    principal = make_principal(
        tenant_id, email=f"{slug}@t.ru", role="member", tenant_slug=slug
    )
    await _register(db, principal, org_role="office")
    return principal


async def _my(db, principal, **kw):
    """list_my_tasks с явными Query-дефолтами (FastAPI их напрямую не резолвит)."""
    params = {
        "done": None,
        "status_": None,
        "due_window": None,
        "include_archived": False,
        "include_personal": True,
    }
    params.update(kw)
    return await list_my_tasks(principal=principal, db=db, **params)


async def _assigned_by_me(db, principal, **kw):
    params = {"include_archived": False, "done": False}
    params.update(kw)
    return await list_assigned_by_me(principal=principal, db=db, **params)


# ─── Личные вперемешку с рабочими ───────────────────────────────────────────


@pytest.fixture
async def mixed(db: AsyncSession, tenant_id: uuid.UUID):
    """(я, id личного, id личной задачи, id рабочей задачи)."""
    tag = uuid.uuid4().hex[:8]
    me = await _member(db, tenant_id, f"mm-{tag}")
    personal_id = await ensure_personal_project(db, me)
    project = await create_project(ProjectCreate(name=f"Рабочий {tag}"), me, db)
    await seed_stages(db, project.id, me)
    await db.commit()

    mine = await create_task(personal_id, TaskCreate(title="Купить хлеб"), me, db)
    work = await create_task(
        project.id,
        TaskCreate(title="Свести отчёт", assignee_ids=[me.employee_id]),
        me,
        db,
    )
    await db.commit()
    return me, personal_id, mine.id, work.id


async def test_personal_and_work_in_one_list(db, mixed):
    me, _personal_id, mine_id, work_id = mixed
    ids = {t.id for t in await _my(db, me)}
    assert {mine_id, work_id} <= ids


async def test_include_personal_false_keeps_old_behaviour(db, mixed):
    """Legacy-вход остаётся: вчерашний бандл просит только рабочее."""
    me, _personal_id, mine_id, work_id = mixed
    ids = {t.id for t in await _my(db, me, include_personal=False)}
    assert work_id in ids
    assert mine_id not in ids


async def test_personal_task_without_assignee_stays_visible(db, mixed):
    """Ради этого в предикате вторая ветка.

    Снять исполнителей у личной задачи можно явным пустым списком — и на одном
    `assignee_exists` она исчезла бы с экрана совсем: раньше её показывала
    секция «ЛИЧНОЕ» через ручку проекта, а теперь такой секции нет.
    """
    me, _personal_id, mine_id, _work_id = mixed
    await update_task(mine_id, TaskUpdate(assignee_ids=[]), me, db)
    await db.commit()

    rows = await _my(db, me)
    assert mine_id in {t.id for t in rows}
    row = next(t for t in rows if t.id == mine_id)
    assert row.assignees == []
    # Признак личного проекта отдаётся серверно — клиенту его не вычислить.
    assert row.project_is_personal is True


async def test_work_row_knows_it_is_not_personal(db, mixed):
    me, _personal_id, _mine_id, work_id = mixed
    row = next(t for t in await _my(db, me) if t.id == work_id)
    assert row.project_is_personal is False
    # Счётчики строки заполняет теперь и эта ручка — иначе одна и та же задача
    # выглядела бы по-разному на соседних вкладках экрана.
    assert row.comment_count == 0
    assert row.attachment_count == 0


# ─── «Назначенные мной» ─────────────────────────────────────────────────────


@pytest.fixture
async def delegated(db: AsyncSession, tenant_id: uuid.UUID):
    """(автор, коллега, id рабочей задачи коллеге, id поручения в личное)."""
    tag = uuid.uuid4().hex[:8]
    author = await _member(db, tenant_id, f"ab-{tag}-a")
    mate = await _member(db, tenant_id, f"ab-{tag}-m")
    await ensure_personal_project(db, mate)
    project = await create_project(ProjectCreate(name=f"Общий {tag}"), author, db)
    await seed_stages(db, project.id, author)
    await db.commit()

    work = await create_task(
        project.id,
        TaskCreate(title="Собрать акты", assignee_ids=[mate.employee_id]),
        author,
        db,
    )
    own = await create_task(
        project.id,
        TaskCreate(title="Моя же задача", assignee_ids=[author.employee_id]),
        author,
        db,
    )
    await db.commit()
    personal = await delegate_personal_task(
        DelegateCreate(employee_id=mate.employee_id, title="Позвонить в банк"),
        author,
        db,
    )
    await db.commit()
    return author, mate, project.id, work.id, own.id, personal.id


async def test_assigned_by_me_covers_work_and_personal(db, delegated):
    author, _mate, _pid, work_id, own_id, personal_id = delegated
    ids = {t.id for t in await _assigned_by_me(db, author)}
    # Главное приобретение: задача в ОБЫЧНОМ проекте, а не только поручение.
    assert work_id in ids
    assert personal_id in ids
    # Самоназначенное сюда не попадает — оно и так в соседних вкладках.
    assert own_id not in ids


async def test_assigned_by_me_is_superset_of_delegated(db, delegated):
    author, *_rest = delegated
    old = {t.id for t in await list_delegated(author, db)}
    new = {t.id for t in await _assigned_by_me(db, author)}
    assert old and old <= new


async def test_closed_task_leaves_the_tab(db, delegated):
    author, mate, _pid, work_id, _own, _personal = delegated
    await update_task(work_id, TaskUpdate(done=True), mate, db)
    await db.commit()
    assert work_id not in {t.id for t in await _assigned_by_me(db, author)}


async def test_row_that_would_404_is_not_listed(db, delegated):
    """Убрали из проекта — задача уходит из списка, а не ломается при клике.

    `/me/tasks` этим болеет и сегодня (там членство не проверяется вовсе), но
    повторять ошибку в новой ручке нельзя: строка, которая не открывается,
    хуже отсутствующей.
    """
    author, mate, project_id, work_id, _own, _personal = delegated
    # `remove_member` принимает id СТРОКИ членства, а не сотрудника.
    membership = (
        await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == mate.employee_id,
            )
        )
    ).scalar_one()
    # Убираем ИСПОЛНИТЕЛЯ из проекта и делаем его автором строки: проверяем
    # именно «создал, но больше не участник». Владельца удалить нельзя — в
    # проекте обязан остаться хотя бы один owner.
    await update_task(work_id, TaskUpdate(assignee_ids=[author.employee_id]), author, db)
    await db.commit()
    task = await db.get(Task, work_id)
    task.created_by = mate.employee_id
    await db.commit()
    await remove_member(project_id, membership, author, db)
    await db.commit()

    assert work_id not in {t.id for t in await _assigned_by_me(db, mate)}
    with pytest.raises(HTTPException) as gone:
        await get_task(work_id, mate, db)
    assert gone.value.status_code == 404
    return




async def test_foreign_personal_task_i_did_not_touch_is_hidden(db, tenant_id):
    """Автор ЧУЖОЙ личной задачи, не ставший ни исполнителем, ни наблюдателем.

    Так умеет только hub-admin: обычный сотрудник в чужое личное не пишет.
    Строку ему не показываем — `personal_task_scope` с 15.09 админа не
    пропускает, и карточка ответила бы 404.
    """
    tag = uuid.uuid4().hex[:8]
    owner = await _member(db, tenant_id, f"fp-{tag}-o")
    admin = make_principal(
        tenant_id, email=f"fp-{tag}-a@t.ru", role="admin", tenant_slug=f"fp-{tag}-a"
    )
    await _register(db, admin, org_role="office")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    task = await create_task(
        personal_id,
        TaskCreate(title="Чужая личная", assignee_ids=[owner.employee_id]),
        admin,
        db,
    )
    await db.commit()

    assert task.created_by == admin.employee_id
    assert task.id not in {t.id for t in await _assigned_by_me(db, admin)}


async def test_unsubscribing_loses_the_delegated_task(db, tenant_id):
    """Автор отписался от своего поручения — строка уходит вместе с доступом.

    Вторая половина `personal_list_scope`: членства в чужом личном мало, нужна
    причастность к задаче. Доступ автора к поручению держится именно на
    подписке (`create_task_record(watch_creator=True)`), а колокольчик в
    карточке — само-тумблер. Поведение унаследовано от `personal_task_scope` и
    существовало до вкладки: карточка такому автору отвечает 404. Фиксируем,
    чтобы список и карточка отвечали одинаково, а не расходились.
    """
    tag = uuid.uuid4().hex[:8]
    author = await _member(db, tenant_id, f"un-{tag}-a")
    mate = await _member(db, tenant_id, f"un-{tag}-m")
    await ensure_personal_project(db, mate)
    await db.commit()

    task = await delegate_personal_task(
        DelegateCreate(employee_id=mate.employee_id, title="Позвонить в банк"),
        author,
        db,
    )
    await db.commit()
    assert task.id in {t.id for t in await _assigned_by_me(db, author)}

    await db.execute(
        delete(TaskWatcher).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == author.employee_id,
        )
    )
    await db.commit()

    assert task.id not in {t.id for t in await _assigned_by_me(db, author)}
    with pytest.raises(HTTPException) as err:
        await get_task(task.id, author, db)
    assert err.value.status_code == 404
