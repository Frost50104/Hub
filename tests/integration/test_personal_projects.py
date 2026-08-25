"""Личное пространство сотрудника: проект «Личное».

Проверяем три группы инвариантов:
1. создание — идемпотентное, race-safe, в обход гейта can_create_project;
2. скрытие — проекта нет ни в одном списке, но точечный доступ владельца жив;
3. приватность — приглашённый на одну задачу не читает весь личный список.
"""

from __future__ import annotations

import uuid

import pytest
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar import list_calendar_tasks
from app.api.me import get_me
from app.api.me_tasks import list_my_tasks
from app.api.projects import (
    archive_project,
    create_project,
    get_project,
    list_projects,
    remove_member,
    set_project_folder,
    update_member,
    update_project,
)
from app.api.search import search
from app.api.share import create_project_share
from app.api.stats import get_stats
from app.api.tasks import create_task, delete_task, get_task, list_tasks
from app.api.timeline import get_timeline
from app.models.project import Project, ProjectMember
from app.models.stage import ProjectStage
from app.models.task import Task
from app.schemas.project import (
    ProjectCreate,
    ProjectFolderAssign,
    ProjectMemberUpdate,
    ProjectUpdate,
)
from app.schemas.share import ShareCreate
from app.schemas.task import TaskCreate
from app.services.onboarding import GUIDE_TASK_TITLE
from app.services.personal_projects import (
    PERSONAL_KEY_BASE,
    PERSONAL_PROJECT_NAME,
    ensure_personal_project,
    get_personal_project_id,
)
from app.services.project_access import ensure_project_member
from tests.integration.conftest import make_principal
from tests.integration.test_project_access import _register

pytestmark = pytest.mark.integration


async def _member(
    db: AsyncSession, tenant_id: uuid.UUID, slug: str, *, role: str = "member",
    org_role: str | None = "office", email: str | None = None,
) -> Principal:
    principal = make_principal(
        tenant_id,
        email=email or f"{slug}@t.ru",
        role=role,
        tenant_slug=slug,
    )
    await _register(db, principal, org_role=org_role)
    return principal


async def _tasks(db: AsyncSession, project_id: uuid.UUID, principal: Principal):
    """list_tasks с явными Query-дефолтами (напрямую FastAPI их не резолвит)."""
    return await list_tasks(
        project_id,
        include_archived=False,
        done=None,
        status_=None,
        assignee_id=None,
        section_id=None,
        priority=None,
        label=None,
        due_from=None,
        due_to=None,
        sort="position",
        order="asc",
        principal=principal,
        db=db,
        stage_id=None,
    )


async def _my_tasks(db: AsyncSession, principal: Principal, *, personal: bool = False):
    return await list_my_tasks(
        done=None,
        status_=None,
        due_window=None,
        include_archived=False,
        include_personal=personal,
        principal=principal,
        db=db,
    )


# ─── Создание ───────────────────────────────────────────────────────────────


async def test_guide_task_is_created_once(db, tenant_id):
    """Задача-инструкция привязана к СОЗДАНИЮ проекта, а не к каждому входу."""
    principal = await _member(db, tenant_id, "pp-guide-once")
    project_id = await ensure_personal_project(db, principal)
    await db.commit()

    for _ in range(3):
        assert await ensure_personal_project(db, principal) == project_id
        await db.commit()

    count = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.project_id == project_id, Task.title == GUIDE_TASK_TITLE)
        )
    ).scalar_one()
    assert count == 1

    # Удалили — обратно не возвращается: повторное создание задачи было бы
    # спамом (бэкфилл для нынешних сотрудников гоняется один раз вручную).
    task_id = (
        await db.execute(select(Task.id).where(Task.project_id == project_id))
    ).scalar_one()
    await delete_task(task_id, principal, db)
    await db.commit()
    assert await ensure_personal_project(db, principal) == project_id
    await db.commit()
    left = (
        await db.execute(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
    ).scalar_one()
    assert left == 0


async def test_ensure_creates_project_stages_and_owner(db, tenant_id):
    principal = await _member(db, tenant_id, "pp-create")
    project_id = await ensure_personal_project(db, principal)
    await db.commit()

    project = await db.get(Project, project_id)
    assert project is not None
    assert project.name == PERSONAL_PROJECT_NAME
    assert project.key.startswith(PERSONAL_KEY_BASE)
    assert project.personal_owner_id == principal.employee_id

    stages = (
        await db.execute(
            select(ProjectStage.name)
            .where(ProjectStage.project_id == project_id)
            .order_by(ProjectStage.position)
        )
    ).scalars().all()
    assert stages == ["К выполнению", "В работе", "На проверке", "Готово"]

    # Первый вход заводит и задачу-инструкцию — ровно одну, в этом же проекте.
    guide_titles = (
        await db.execute(select(Task.title).where(Task.project_id == project_id))
    ).scalars().all()
    assert guide_titles == [GUIDE_TASK_TITLE]

    role = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == principal.employee_id,
            )
        )
    ).scalar_one()
    assert role == "owner"


async def test_ensure_is_idempotent(db, tenant_id):
    principal = await _member(db, tenant_id, "pp-idem")
    first = await ensure_personal_project(db, principal)
    await db.commit()
    second = await ensure_personal_project(db, principal)
    await db.commit()
    assert first == second

    count = (
        await db.execute(
            select(Project.id).where(Project.personal_owner_id == principal.employee_id)
        )
    ).all()
    assert len(count) == 1


async def test_ensure_bypasses_can_create_gate(db, tenant_id):
    """Линейный employee проектов не создаёт, но личное у него есть."""
    principal = await _member(db, tenant_id, "pp-line", org_role="employee")
    me = await get_me(principal=principal, db=db)
    assert me.can_create_projects is False
    assert me.personal_project_id is not None


async def test_me_carries_ready_guide_links(db, tenant_id):
    """Ссылка на инструкцию приходит ГОТОВОЙ вместе с /me.

    Получать её по клику нельзя: `window.open` после await блокируют
    попап-фильтры. Роль решает здесь, а не на отдаче — та проверяет подпись.
    """
    member = await _member(db, tenant_id, "pp-guide-links")
    rows = (await get_me(principal=member, db=db)).guides
    assert [r.kind for r in rows] == ["employee"]
    assert rows[0].url.startswith("/api/guides/employee?e=")

    admin = await _member(db, tenant_id, "pp-guide-adm", role="admin", org_role=None)
    assert [r.kind for r in (await get_me(principal=admin, db=db)).guides] == [
        "admin",
        "employee",
    ]


async def test_ensure_for_hub_viewer(db, tenant_id):
    """hub:viewer тоже получает своё пространство: личное без права писать
    бессмысленно, а радиус ограничен его же скрытым проектом."""
    principal = await _member(db, tenant_id, "pp-view", role="viewer", org_role=None)
    project_id = await ensure_personal_project(db, principal)
    await db.commit()
    assert project_id is not None


async def test_ensure_skips_principal_without_hub_role(db, tenant_id):
    principal = Principal(
        employee_id=uuid.uuid4(),
        email="other-product@t.ru",
        tenant_id=tenant_id,
        tenant_slug="pp-nohub",
        full_name="Чужой продукт",
        product_roles={},
        jti=str(uuid.uuid4()),
    )
    assert await ensure_personal_project(db, principal) is None


async def test_ensure_recovers_after_key_collision(db, tenant_id):
    """Ключ личного проекта занят обычным — ensure берёт следующий свободный."""
    owner = await _member(db, tenant_id, "pp-key")
    manual = await create_project(
        ProjectCreate(name="Личное", key=PERSONAL_KEY_BASE), owner, db
    )
    assert manual.is_personal is False

    project_id = await ensure_personal_project(db, owner)
    await db.commit()
    project = await db.get(Project, project_id)
    # Суффикс не фиксируем: allocate_personal_key полагается на RLS, а под
    # дефолтной (superuser) ролью тестов он видит ключи всех тенантов сюиты.
    assert project.key != PERSONAL_KEY_BASE
    assert project.key.startswith(PERSONAL_KEY_BASE)


async def test_two_employees_get_distinct_keys(db, tenant_id):
    first = await _member(db, tenant_id, "pp-two-a")
    second = await _member(db, tenant_id, "pp-two-b")
    a = await ensure_personal_project(db, first)
    await db.commit()
    b = await ensure_personal_project(db, second)
    await db.commit()
    keys = [(await db.get(Project, a)).key, (await db.get(Project, b)).key]
    assert keys[0] != keys[1]
    assert all(k.startswith(PERSONAL_KEY_BASE) for k in keys)


async def test_ensure_survives_integrity_error(db, tenant_id, database_url):
    """Гонка: конкурент вставил личный проект между нашим SELECT и INSERT.

    Регресс на SAVEPOINT: без begin_nested IntegrityError аборти́л бы всю
    транзакцию /api/me вместе с привязкой learn-профиля.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    principal = await _member(db, tenant_id, "pp-race")
    await db.commit()

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as other:
        await other.execute(
            select(Project.id).limit(1)
        )  # прогреваем соединение
        winner = await ensure_personal_project(other, principal)
        await other.commit()
    await engine.dispose()

    # Наша сессия ещё не знает о конкуренте — SELECT в ensure сходит заново.
    mine = await ensure_personal_project(db, principal)
    await db.commit()
    assert mine == winner

    # Транзакция жива: обычная работа после гонки проходит.
    project = await create_project(ProjectCreate(name="После гонки"), principal, db)
    assert project.id is not None


# ─── Скрытие из списков ─────────────────────────────────────────────────────


async def test_personal_hidden_from_list_projects(db, tenant_id):
    owner = await _member(db, tenant_id, "pp-hide")
    await create_project(ProjectCreate(name="Рабочий"), owner, db)
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    admin = await _member(db, tenant_id, "pp-hide-adm", role="admin", org_role=None)
    await db.commit()

    for principal in (owner, admin):
        listed = await list_projects(
            include_archived=False, principal=principal, db=db
        )
        assert personal_id not in [p.id for p in listed]
        assert "Рабочий" in [p.name for p in listed]

    # Архивные тоже не всплывают.
    listed = await list_projects(include_archived=True, principal=owner, db=db)
    assert personal_id not in [p.id for p in listed]


async def test_personal_visible_via_get_project_detail(db, tenant_id):
    owner = await _member(db, tenant_id, "pp-detail")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    resp = await get_project(personal_id, owner, db)
    assert resp.is_personal is True
    assert resp.can_edit is True and resp.can_manage is True


async def test_search_hides_foreign_personal(db, tenant_id):
    owner = await _member(db, tenant_id, "pp-search")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    await create_task(
        personal_id, TaskCreate(title="Записаться к стоматологу"), owner, db
    )
    await db.commit()

    found = await search(q="стоматолог", group_by=None, principal=owner, db=db)
    assert any("стоматолог" in t.title.lower() for t in found.tasks)

    admin = await _member(db, tenant_id, "pp-search-adm", role="admin", org_role=None)
    await db.commit()
    as_admin = await search(q="стоматолог", group_by=None, principal=admin, db=db)
    assert as_admin.tasks == []

    # Личное не всплывает и как проект — даже владельцу.
    by_name = await search(q="Личное", group_by=None, principal=owner, db=db)
    assert personal_id not in [p.id for p in by_name.projects]


async def test_assistant_hides_foreign_personal(db, tenant_id):
    from app.services.assistant.context import NotFound, ToolContext, resolve_project
    from app.services.assistant.tools import t_list_projects

    owner = await _member(db, tenant_id, "pp-ai")
    await ensure_personal_project(db, owner)
    await db.commit()

    ctx = ToolContext(db=db, principal=owner, profile=None)
    listed = await t_list_projects(ctx, None)
    assert PERSONAL_PROJECT_NAME not in [p["name"] for p in listed["projects"]]
    # Но резолв по имени работает — «создай мне личную задачу».
    resolved = await resolve_project(ctx, PERSONAL_PROJECT_NAME)
    assert resolved.personal_owner_id == owner.employee_id

    admin = await _member(db, tenant_id, "pp-ai-adm", role="admin", org_role=None)
    await db.commit()
    admin_ctx = ToolContext(db=db, principal=admin, profile=None)
    # По UUID, а не по имени: под superuser-ролью тестов запрос админа видит и
    # чужие тенанты, где может лежать ОБЫЧНЫЙ проект с именем «Личное».
    with pytest.raises(NotFound):
        await resolve_project(admin_ctx, str(resolved.id))


def _guide_id(tasks):
    """Id задачи-инструкции, которую Hub заводит вместе с личным проектом."""
    return next(t.id for t in tasks if t.title == GUIDE_TASK_TITLE)


# ─── Приватность внутри чужого личного ──────────────────────────────────────


async def _shared_personal(db, tenant_id, slug):
    """(владелец, гость, id личного проекта, id задачи гостя, id личной задачи)."""
    owner = await _member(db, tenant_id, f"{slug}-o")
    guest = await _member(db, tenant_id, f"{slug}-g", email=f"{slug}-guest@t.ru")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    shared = await create_task(
        personal_id,
        TaskCreate(title="Забрать акты", assignee_ids=[guest.employee_id]),
        owner,
        db,
    )
    private = await create_task(
        personal_id, TaskCreate(title="Записаться к врачу"), owner, db
    )
    await db.commit()
    return owner, guest, personal_id, shared.id, private.id


async def test_guest_sees_only_assigned_task(db, tenant_id):
    owner, guest, personal_id, shared_id, private_id = await _shared_personal(
        db, tenant_id, "pp-guest"
    )
    # Назначение выдало гостю viewer-членство — но список ему урезан.
    visible = await _tasks(db, personal_id, guest)
    assert [t.id for t in visible] == [shared_id]

    owner_view = await _tasks(db, personal_id, owner)
    # Третья задача — та, что Hub завёл при создании личного проекта
    # (`onboarding.create_guide_task`): она тоже принадлежит владельцу.
    assert {t.id for t in owner_view} == {shared_id, private_id, _guide_id(owner_view)}
    assert GUIDE_TASK_TITLE in {t.title for t in owner_view}


async def test_guest_cannot_open_private_task(db, tenant_id):
    from fastapi import HTTPException

    _owner, guest, _pid, shared_id, private_id = await _shared_personal(
        db, tenant_id, "pp-guest2"
    )
    assert (await get_task(shared_id, guest, db)).id == shared_id
    with pytest.raises(HTTPException) as exc:
        await get_task(private_id, guest, db)
    assert exc.value.status_code == 404


async def test_guest_closes_assigned_task(db, tenant_id):
    """Ради чего затевалось: поручил коллеге — коллега может отметить «Готово»."""
    from fastapi import HTTPException

    from app.api.tasks import update_task
    from app.schemas.task import TaskUpdate

    _owner, guest, _pid, shared_id, _private = await _shared_personal(
        db, tenant_id, "pp-guest-done"
    )
    updated = await update_task(shared_id, TaskUpdate(done=True), guest, db)
    assert updated.done is True

    # Но переименовать чужую личную задачу он не вправе.
    with pytest.raises(HTTPException) as exc:
        await update_task(shared_id, TaskUpdate(title="Моё"), guest, db)
    assert exc.value.status_code == 403


async def test_guest_blocked_from_aggregates(db, tenant_id):
    from fastapi import HTTPException

    _owner, guest, personal_id, _shared, _private = await _shared_personal(
        db, tenant_id, "pp-guest3"
    )
    for call in (
        lambda: get_stats(personal_id, guest, db),
        lambda: list_calendar_tasks(
            personal_id,
            from_="2026-08-01",
            to="2026-08-31",
            done=None,
        status_=None,
            assignee_id=None,
            priority=None,
            principal=guest,
            db=db,
        ),
        lambda: get_timeline(
            personal_id,
            from_="2026-08-01",
            to="2026-08-31",
            include_undated=False,
            principal=guest,
            db=db,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 403


async def test_admin_keeps_pointwise_access(db, tenant_id):
    """Решение владельца: точечный доступ админа по ссылке остаётся."""
    _owner, _guest, personal_id, _shared, private_id = await _shared_personal(
        db, tenant_id, "pp-adm-point"
    )
    admin = await _member(db, tenant_id, "pp-adm-point-a", role="admin", org_role=None)
    await db.commit()
    assert (await get_task(private_id, admin, db)).id == private_id
    # Две созданные тестом задачи + задача-инструкция от первого входа.
    assert len(await _tasks(db, personal_id, admin)) == 3


# ─── /me/tasks ──────────────────────────────────────────────────────────────


async def test_me_tasks_excludes_own_personal(db, tenant_id):
    owner = await _member(db, tenant_id, "pp-me")
    work = await create_project(ProjectCreate(name="Рабочий"), owner, db)
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    work_task = await create_task(
        work.id,
        TaskCreate(title="Рабочая", assignee_ids=[owner.employee_id]),
        owner,
        db,
    )
    personal_task = await create_task(
        personal_id,
        TaskCreate(title="Личная", assignee_ids=[owner.employee_id]),
        owner,
        db,
    )
    await db.commit()

    default = await _my_tasks(db, owner)
    ids = [t.id for t in default]
    # Регресс на NULL-семантику: рабочие задачи не должны пропасть.
    assert work_task.id in ids
    assert personal_task.id not in ids

    with_personal = await _my_tasks(db, owner, personal=True)
    assert personal_task.id in [t.id for t in with_personal]


async def test_me_tasks_keeps_foreign_personal(db, tenant_id):
    """Задача, назначенная мне в ЧУЖОМ личном, — обычная работа."""
    _owner, guest, _pid, shared_id, _private = await _shared_personal(
        db, tenant_id, "pp-me-foreign"
    )
    assert shared_id in [t.id for t in await _my_tasks(db, guest)]


# ─── Инварианты ─────────────────────────────────────────────────────────────


async def test_personal_project_invariants(db, tenant_id):
    from fastapi import HTTPException

    owner = await _member(db, tenant_id, "pp-inv")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    project = await db.get(Project, personal_id)

    with pytest.raises(HTTPException) as exc:
        await archive_project(personal_id, owner, db)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await set_project_folder(
            personal_id, ProjectFolderAssign(folder_id=None), owner, db
        )
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await create_project_share(
            personal_id, ShareCreate(expires_at=None), owner, db
        )
    assert exc.value.status_code in (409, 503)

    # Переименование разрешено: скрытость держится колонкой, а не именем.
    renamed = await update_project(
        personal_id, ProjectUpdate(name="Мои дела"), owner, db
    )
    assert renamed.name == "Мои дела"
    assert renamed.is_personal is True
    assert project.personal_owner_id == owner.employee_id


async def test_personal_owner_cannot_leave(db, tenant_id):
    from fastapi import HTTPException

    owner = await _member(db, tenant_id, "pp-leave")
    guest = await _member(db, tenant_id, "pp-leave-g", email="pp-leave-g@t.ru")
    personal_id = await ensure_personal_project(db, owner)
    await ensure_project_member(
        db,
        project_id=personal_id,
        tenant_id=tenant_id,
        employee_id=guest.employee_id,
        role="owner",
    )
    await db.commit()

    membership = (
        await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == personal_id,
                ProjectMember.employee_id == owner.employee_id,
            )
        )
    ).scalar_one()

    with pytest.raises(HTTPException) as exc:
        await remove_member(personal_id, membership, owner, db)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await update_member(
            personal_id, membership, ProjectMemberUpdate(role="viewer"), owner, db
        )
    assert exc.value.status_code == 409


async def test_get_personal_project_id_is_tenant_scoped(db, tenant_id):
    """RLS: личный проект чужого тенанта невидим (fail-closed)."""
    owner = await _member(db, tenant_id, "pp-rls")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()
    assert await get_personal_project_id(db, owner.employee_id) == personal_id

    stranger = uuid.uuid4()
    assert await get_personal_project_id(db, stranger) is None
