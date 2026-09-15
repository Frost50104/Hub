"""Личное пространство сотрудника: проект «Личное».

Проверяем три группы инвариантов:
1. создание — идемпотентное, race-safe, в обход гейта can_create_project;
2. скрытие — проекта нет ни в одном списке, но точечный доступ владельца жив;
3. приватность — приглашённый на одну задачу не читает весь личный список.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar import list_calendar_tasks
from app.api.me import get_me
from app.api.me_delegate import DelegateCreate, delegate_personal_task, list_delegated
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
from app.api.tasks import (
    add_task_assignee,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)
from app.api.timeline import get_timeline
from app.models.project import Project, ProjectMember
from app.models.stage import ProjectStage
from app.models.task import Task, TaskAssignee
from app.schemas.project import (
    ProjectCreate,
    ProjectFolderAssign,
    ProjectMemberUpdate,
    ProjectUpdate,
)
from app.schemas.share import ShareCreate
from app.schemas.task import TaskAssigneeAdd, TaskCreate, TaskUpdate
from app.services.onboarding import GUIDE_TASK_TITLE
from app.services.personal_projects import (
    PERSONAL_PROJECT_NAME,
    ensure_personal_project,
    get_personal_project_id,
    personal_key_base,
)
from app.services.project_access import ensure_project_member
from app.services.task_assignees import (
    apply_assignee_side_effects,
    set_task_assignees,
)
from tests.integration.conftest import make_principal, seed_stages
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


async def test_ensure_creates_project_without_stages(db, tenant_id):
    principal = await _member(db, tenant_id, "pp-create")
    project_id = await ensure_personal_project(db, principal)
    await db.commit()

    project = await db.get(Project, project_id)
    assert project is not None
    assert project.name == PERSONAL_PROJECT_NAME
    # Ключ из ФИО владельца (16.09), а не общий префикс на тенант: «LICNOE26-5»
    # человеку ничего не говорило.
    assert project.key.startswith(personal_key_base(principal.full_name))
    assert project.personal_owner_id == principal.employee_id

    # Колонок нет: личное пространство — список дел, а не доска, и задачи здесь
    # и так заводятся без колонки. Раньше проект получал четвёрку стартовых,
    # которую владелец не видел ни на одном экране.
    stages = (
        await db.execute(
            select(ProjectStage.name)
            .where(ProjectStage.project_id == project_id)
            .order_by(ProjectStage.position)
        )
    ).scalars().all()
    assert stages == []

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
    """Ключ личного занят ОБЫЧНЫМ проектом — ensure берёт следующий свободный.

    Namespace ключей общий (`UNIQUE(tenant_id, key)`), поэтому «POPOV» вполне
    может оказаться у рабочего проекта раньше, чем у Попова появится личный.
    """
    owner = await _member(db, tenant_id, "pp-key")
    base = personal_key_base(owner.full_name)
    manual = await create_project(ProjectCreate(name="Ручной", key=base), owner, db)
    assert manual.is_personal is False

    project_id = await ensure_personal_project(db, owner)
    await db.commit()
    project = await db.get(Project, project_id)
    assert project.key != base
    assert project.key.startswith(base)


async def test_namesakes_get_distinct_keys(db, tenant_id):
    """Полные тёзки — единственный источник коллизий после 16.09.

    На проде таких 4 группы из 178: база из ФИО совпадает, различает их только
    цифровой суффикс. Признака «кто есть кто» в ключе не будет — это принято.
    """
    first = await _member(db, tenant_id, "pp-two-a")
    second = await _member(db, tenant_id, "pp-two-b")
    assert first.full_name == second.full_name
    a = await ensure_personal_project(db, first)
    await db.commit()
    b = await ensure_personal_project(db, second)
    await db.commit()
    keys = [(await db.get(Project, a)).key, (await db.get(Project, b)).key]
    base = personal_key_base(first.full_name)
    assert keys[0] != keys[1]
    assert all(k.startswith(base) for k in keys)


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

    # Личное не всплывает и как проект — даже владельцу. Константой, а не
    # литералом: после переименования (16.09) литерал «Личное» продолжил бы
    # проходить, ничего не проверяя.
    by_name = await search(
        q=PERSONAL_PROJECT_NAME, group_by=None, principal=owner, db=db
    )
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
    # И по слову «личное» тоже: проект так назывался до 16.09, люди продолжат
    # говорить именно так, а ни точное совпадение, ни `ilike` его больше не
    # найдут — синоним держит `_PERSONAL_SYNONYMS`.
    for phrase in ("личное", "Личное", "мои задачи", "личный проект"):
        assert (await resolve_project(ctx, phrase)).id == resolved.id

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


# ─── Поручение задачи в ЧУЖОЕ личное (15.09) ────────────────────────────────


async def _delegated(db, tenant_id, slug):
    """(автор, получатель, id личного получателя, поручённая задача).

    Строится «снизу вверх», в отличие от `_shared_personal`: задачу заводит
    ПОСТОРОННИЙ, а не владелец личного. До 15.09 такой путь был закрыт вовсе —
    `POST /projects/{id}/tasks` отвечал автору 404.
    """
    author = await _member(db, tenant_id, f"{slug}-a")
    target = await _member(db, tenant_id, f"{slug}-t", email=f"{slug}-target@t.ru")
    personal_id = await ensure_personal_project(db, target)
    # Личная заметка получателя — её автор видеть НЕ должен.
    await create_task(personal_id, TaskCreate(title="Записаться к врачу"), target, db)
    await db.commit()

    task = await delegate_personal_task(
        DelegateCreate(employee_id=target.employee_id, title="Собрать акты"),
        author,
        db,
    )
    return author, target, personal_id, task


async def test_delegate_puts_task_into_personal_inbox(db, tenant_id):
    author, target, personal_id, task = await _delegated(db, tenant_id, "dl-put")
    assert task.project_id == personal_id
    # Исполнитель — получатель, а не автор: иначе задача осела бы у автора.
    assert [a.employee_id for a in task.assignees] == [target.employee_id]
    # Личная задача заводится без колонки — это список дел, а не доска.
    assert task.stage_id is None


async def test_author_sees_only_delegated_task(db, tenant_id):
    author, target, personal_id, task = await _delegated(db, tenant_id, "dl-scope")
    # Ровно то, ради чего затевалось: автор видит СВОЮ задачу и ничего больше.
    visible = await _tasks(db, personal_id, author)
    assert [t.id for t in visible] == [task.id]

    # А получатель видит и её, и свою заметку, и задачу-инструкцию.
    owner_view = await _tasks(db, personal_id, target)
    assert task.id in {t.id for t in owner_view}
    assert len(owner_view) == 3


async def test_author_cannot_open_other_personal_tasks(db, tenant_id):
    author, target, personal_id, _task = await _delegated(db, tenant_id, "dl-private")
    private = next(
        t for t in await _tasks(db, personal_id, target) if t.title == "Записаться к врачу"
    )
    with pytest.raises(HTTPException) as err:
        await get_task(private.id, author, db)
    # 404, а не 403: существование чужой личной задачи скрываем.
    assert err.value.status_code == 404


async def test_author_blocked_from_aggregates(db, tenant_id):
    author, _target, personal_id, _task = await _delegated(db, tenant_id, "dl-aggr")
    with pytest.raises(HTTPException) as err:
        await get_stats(personal_id, principal=author, db=db)
    assert err.value.status_code == 403


async def test_author_gets_no_counts_of_foreign_personal(db, tenant_id):
    author, _target, personal_id, _task = await _delegated(db, tenant_id, "dl-counts")
    # Членство открывает карточку проекта — но не число чужих заметок в ней.
    as_guest = await get_project(personal_id, author, db)
    assert as_guest.task_count is None
    assert as_guest.done_count is None


async def test_author_edits_and_withdraws_own_delegation(db, tenant_id):
    author, _target, _personal_id, task = await _delegated(db, tenant_id, "dl-edit")
    # Автор там viewer, но СВОЮ задачу правит: иначе опечатку не исправить.
    updated = await update_task(task.id, TaskUpdate(title="Собрать акты до пятницы"), author, db)
    assert updated.title == "Собрать акты до пятницы"
    # И отзывает её целиком.
    await delete_task(task.id, author, db)
    assert await db.get(Task, task.id) is None


async def test_target_can_close_delegated_task(db, tenant_id):
    _author, target, _personal_id, task = await _delegated(db, tenant_id, "dl-close")
    done = await update_task(task.id, TaskUpdate(done=True), target, db)
    assert done.done is True


async def test_delegated_shows_up_in_my_section(db, tenant_id):
    author, target, _personal_id, task = await _delegated(db, tenant_id, "dl-list")
    mine = await list_delegated(author, db)
    assert [t.id for t in mine] == [task.id]
    # Закрытые уходят из секции: «Я поставил» — про незавершённое.
    await update_task(task.id, TaskUpdate(done=True), target, db)
    await db.commit()
    assert await list_delegated(author, db) == []
    # И чужие поручения в свою секцию не подмешиваются.
    assert await list_delegated(target, db) == []


async def test_delegate_refuses_self(db, tenant_id):
    author = await _member(db, tenant_id, "dl-self")
    await ensure_personal_project(db, author)
    await db.commit()
    with pytest.raises(HTTPException) as err:
        await delegate_personal_task(
            DelegateCreate(employee_id=author.employee_id, title="Сам себе"), author, db
        )
    assert err.value.status_code == 400


async def test_delegate_refuses_when_target_never_logged_in(db, tenant_id):
    author = await _member(db, tenant_id, "dl-new-a")
    target = await _member(db, tenant_id, "dl-new-t", email="dl-new-target@t.ru")
    # Личного пространства у получателя нет — оно заводится при первом входе.
    with pytest.raises(HTTPException) as err:
        await delegate_personal_task(
            DelegateCreate(employee_id=target.employee_id, title="Подготовить смену"),
            author,
            db,
        )
    assert err.value.status_code == 409


# ─── Задача едет к исполнителю (15.09) ──────────────────────────────────────


async def _pair(db, tenant_id, slug):
    """Двое с готовыми личными пространствами: (я, коллега, моё, его)."""
    me = await _member(db, tenant_id, f"{slug}-me")
    mate = await _member(db, tenant_id, f"{slug}-mate", email=f"{slug}-mate@t.ru")
    mine = await ensure_personal_project(db, me)
    theirs = await ensure_personal_project(db, mate)
    await db.commit()
    return me, mate, mine, theirs


async def _members(db, project_id):
    return set(
        (
            await db.execute(
                select(ProjectMember.employee_id).where(
                    ProjectMember.project_id == project_id
                )
            )
        )
        .scalars()
        .all()
    )


async def test_assigning_colleague_hands_the_task_over(db, tenant_id):
    """Решение владельца 15.09: «назначили лично мне — вижу в СВОЁМ личном».

    До этого задача оставалась у автора, а исполнитель видел её только в
    кросс-проектном списке и на странице ЧУЖОГО «Личного».
    """
    me, mate, mine, theirs = await _pair(db, tenant_id, "ho-basic")
    # Заметка «для себя» — чтобы номера в двух проектах разошлись и было
    # видно, что задача перенумеровалась, а не просто сменила project_id.
    await create_task(mine, TaskCreate(title="Купить хлеб"), me, db)
    task = await create_task(
        mine,
        TaskCreate(title="Забрать акты", assignee_ids=[mate.employee_id]),
        me,
        db,
    )
    await db.commit()

    assert task.project_id == theirs
    assert [a.employee_id for a in task.assignees] == [mate.employee_id]
    # В моём личном она была третьей (инструкция + хлеб), в его — вторая:
    # номер «KEY-42» уникален внутри проекта, и переезд его перевыдаёт.
    assert task.seq == 2

    # Получателю задача видна у себя, автору — только она одна.
    assert task.id in {t.id for t in await _tasks(db, theirs, mate)}
    assert [t.id for t in await _tasks(db, theirs, me)] == [task.id]
    # Членство автору — явным шагом: без него карточка ответила бы 404.
    assert me.employee_id in await _members(db, theirs)
    assert (await get_task(task.id, me, db)).id == task.id
    # В своём личном автор её больше не видит — она уехала.
    assert task.id not in {t.id for t in await _tasks(db, mine, me)}


async def test_handed_over_task_lands_in_my_delegated(db, tenant_id):
    """«Я поставил» показывает и поручения, и переданные задачи.

    Условие секции — `created_by = я` в чужом личном, а после переезда задача
    ровно такая. Отдельной ветки не понадобилось.
    """
    me, mate, mine, _theirs = await _pair(db, tenant_id, "ho-deleg")
    task = await create_task(
        mine, TaskCreate(title="Свести отчёт", assignee_ids=[mate.employee_id]), me, db
    )
    await db.commit()
    assert [t.id for t in await list_delegated(me, db)] == [task.id]


async def test_handoff_does_not_open_the_rest_of_personal(db, tenant_id):
    """Автор получил членство в чужом личном — и всё равно видит одну задачу."""
    me, mate, mine, theirs = await _pair(db, tenant_id, "ho-priv")
    private = await create_task(
        theirs, TaskCreate(title="Записаться к врачу"), mate, db
    )
    task = await create_task(
        mine, TaskCreate(title="Позвонить в банк", assignee_ids=[mate.employee_id]), me, db
    )
    await db.commit()

    assert [t.id for t in await _tasks(db, theirs, me)] == [task.id]
    with pytest.raises(HTTPException) as err:
        await get_task(private.id, me, db)
    assert err.value.status_code == 404
    # Агрегаты чужого личного закрыты и после переезда.
    with pytest.raises(HTTPException) as stats_err:
        await get_stats(theirs, principal=me, db=db)
    assert stats_err.value.status_code == 403


async def test_patch_assignees_hands_the_task_over(db, tenant_id):
    """Тот же путь из карточки: сменили исполнителя — задача уехала."""
    me, mate, mine, theirs = await _pair(db, tenant_id, "ho-patch")
    task = await create_task(mine, TaskCreate(title="Купить бумагу"), me, db)
    await db.commit()
    # Личная задача заводится на владельца — замена, а не добавление.
    assert [a.employee_id for a in task.assignees] == [me.employee_id]

    updated = await update_task(
        task.id, TaskUpdate(assignee_ids=[mate.employee_id]), me, db
    )
    await db.commit()
    assert updated.project_id == theirs
    assert [a.employee_id for a in updated.assignees] == [mate.employee_id]


async def test_handoff_is_reversible(db, tenant_id):
    """Получатель вернул задачу автору — она уехала обратно к нему.

    Правило симметрично по построению: `assert_movable` смотрит на источник
    («мой личный») и на исполнителя, а не на историю задачи.
    """
    me, mate, mine, theirs = await _pair(db, tenant_id, "ho-back")
    task = await create_task(
        mine, TaskCreate(title="Сверить остатки", assignee_ids=[mate.employee_id]), me, db
    )
    await db.commit()
    assert task.project_id == theirs

    back = await update_task(task.id, TaskUpdate(assignee_ids=[me.employee_id]), mate, db)
    await db.commit()
    assert back.project_id == mine
    assert mate.employee_id in await _members(db, mine)


async def test_two_assignees_in_personal_are_refused(db, tenant_id):
    """«Положить задачу в два личных» невозможно физически — говорим прямо."""
    me, mate, mine, _theirs = await _pair(db, tenant_id, "ho-two")
    task = await create_task(mine, TaskCreate(title="Смета"), me, db)
    await db.commit()

    with pytest.raises(HTTPException) as err:
        await add_task_assignee(
            task.id, TaskAssigneeAdd(employee_id=mate.employee_id), me, db
        )
    assert err.value.status_code == 409
    assert "один исполнитель" in err.value.detail
    # Ручка не пишет наполовину: транзакция откатывается целиком.
    await db.rollback()
    fresh = await db.get(Task, task.id)
    assert fresh.project_id == mine


async def test_handoff_refuses_subtask(db, tenant_id):
    """Подзадача переезжает только вместе с родителем — иначе семья рвётся."""
    me, mate, mine, _theirs = await _pair(db, tenant_id, "ho-sub")
    parent = await create_task(mine, TaskCreate(title="Ремонт"), me, db)
    await db.commit()
    child = await create_task(
        mine,
        TaskCreate(title="Вызвать мастера", parent_task_id=parent.id, assignee_ids=[]),
        me,
        db,
    )
    await db.commit()

    with pytest.raises(HTTPException) as err:
        await update_task(child.id, TaskUpdate(assignee_ids=[mate.employee_id]), me, db)
    assert err.value.status_code == 409
    assert "Подзадачу" in err.value.detail
    await db.rollback()


async def test_handoff_refuses_when_target_never_logged_in(db, tenant_id):
    """Личное пространство заводится первым входом — раньше его нет."""
    me = await _member(db, tenant_id, "ho-new-me")
    newbie = await _member(db, tenant_id, "ho-new-t", email="ho-new-target@t.ru")
    mine = await ensure_personal_project(db, me)
    await db.commit()

    with pytest.raises(HTTPException) as err:
        await create_task(
            mine,
            TaskCreate(title="Принять смену", assignee_ids=[newbie.employee_id]),
            me,
            db,
        )
    assert err.value.status_code == 409
    assert "ни разу не заходил" in err.value.detail
    await db.rollback()


async def test_work_project_assignment_stays_put(db, tenant_id):
    """Регресс: в обычном проекте назначение никуда задачу не двигает."""
    me, mate, _mine, _theirs = await _pair(db, tenant_id, "ho-work")
    work = await create_project(ProjectCreate(name="Рабочий проект"), me, db)
    await db.commit()
    task = await create_task(
        work.id, TaskCreate(title="Общая", assignee_ids=[mate.employee_id]), me, db
    )
    await db.commit()
    assert task.project_id == work.id

    # И двое исполнителей там по-прежнему законны.
    updated = await update_task(
        task.id,
        TaskUpdate(assignee_ids=[me.employee_id, mate.employee_id]),
        me,
        db,
    )
    await db.commit()
    assert len(updated.assignees) == 2


# ─── Приватность внутри чужого личного ──────────────────────────────────────


async def _shared_personal(db, tenant_id, slug):
    """(владелец, гость, id личного проекта, id задачи гостя, id личной задачи).

    Состояние ЛЕГАСИ и собирается в обход ручек нарочно: с 15.09 назначенная
    коллеге задача уезжает в ЕГО личное (`apply_personal_assignee_rules`), и
    через API «чужой исполнитель в моём личном» больше не получить. Но строки,
    заведённые до 15.09, живут дальше — разовая джоба перенесла только
    невыполненные с одним исполнителем, выполненные остались историей. Значит
    приватность обязана держать их по-прежнему: гость видит свою задачу и ни
    одной чужой.
    """
    owner = await _member(db, tenant_id, f"{slug}-o")
    guest = await _member(db, tenant_id, f"{slug}-g", email=f"{slug}-guest@t.ru")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    created = await create_task(
        personal_id,
        TaskCreate(title="Забрать акты", assignee_ids=[]),
        owner,
        db,
    )
    private = await create_task(
        personal_id, TaskCreate(title="Записаться к врачу"), owner, db
    )
    shared = await db.get(Task, created.id)
    diff = await set_task_assignees(
        db,
        task=shared,
        employee_ids=[guest.employee_id],
        actor_id=owner.employee_id,
    )
    await apply_assignee_side_effects(
        db,
        task=shared,
        diff=diff,
        actor_id=owner.employee_id,
        actor_name="Владелец",
        notify=False,
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


async def test_admin_does_not_see_foreign_personal(db, tenant_id):
    """Решение владельца 15.09: админ в чужом личном — такой же гость.

    Прежде у него был точечный доступ по прямой ссылке («разобраться, когда
    человек просит помочь»). Владелец зашёл под админской учёткой, увидел в
    чужом личном проекте чужие заметки и сказал: «я не должен видеть её личные
    задачи, где я не участник».
    """
    _owner, _guest, personal_id, _shared, private_id = await _shared_personal(
        db, tenant_id, "pp-adm-point"
    )
    admin = await _member(db, tenant_id, "pp-adm-point-a", role="admin", org_role=None)
    await db.commit()
    # 404, а не 403: существование чужой личной задачи скрываем и от админа.
    with pytest.raises(HTTPException) as err:
        await get_task(private_id, admin, db)
    assert err.value.status_code == 404
    # Список пуст: он там никто — ни исполнитель, ни наблюдатель.
    assert await _tasks(db, personal_id, admin) == []
    # Удалить то, чего не видит, тоже нельзя — иначе «не вижу, но стираю».
    with pytest.raises(HTTPException) as del_err:
        await delete_task(private_id, admin, db)
    assert del_err.value.status_code == 404
    # Агрегаты — 403, как любому приглашённому.
    with pytest.raises(HTTPException) as stats_err:
        await get_stats(personal_id, principal=admin, db=db)
    assert stats_err.value.status_code == 403


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


# ─── Статус личной задачи ───────────────────────────────────────────────────


async def test_personal_task_is_created_without_stage(db, tenant_id):
    """Личное — список дел, а не доска: у новой задачи статус пустой.

    До этого `create_task_record` клал задачу в первую колонку проекта, и
    каждая личная задача молча оседала в «К выполнению» — колонке, которую
    владелец никогда не выбирал и на доску которой не смотрит.
    """
    owner = await _member(db, tenant_id, "pp-nostage")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    task = await create_task(personal_id, TaskCreate(title="Купить хлеб"), owner, db)
    await db.commit()
    assert task.stage_id is None

    # Задача-инструкция заводится тем же путём — значит тоже без статуса.
    guide = (
        await db.execute(
            select(Task.stage_id).where(
                Task.project_id == personal_id, Task.title == GUIDE_TASK_TITLE
            )
        )
    ).scalar_one()
    assert guide is None


async def test_personal_task_keeps_explicit_stage(db, tenant_id):
    """Прочерк — только ДЕФОЛТ. Попросили колонку — задача в ней."""
    owner = await _member(db, tenant_id, "pp-explicit")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    # Колонку заводим явно: проект (и личный тоже) рождается без колонок, и без
    # сида `stage_id` был бы None — тест сравнивал бы None с None и молчал.
    [stage] = await seed_stages(db, personal_id, owner, names=("Сегодня",))
    task = await create_task(
        personal_id, TaskCreate(title="На доску", stage_id=stage.id), owner, db
    )
    await db.commit()
    assert task.stage_id == stage.id


async def test_work_task_still_lands_in_first_stage(db, tenant_id):
    """Регресс: в проекте С КОЛОНКАМИ дефолт прежний — первая по позиции.

    Колонки создаём сами: проект их больше не приносит, а без сида тест
    сравнивал бы None с None и проходил бы, ничего не проверяя.
    """
    owner = await _member(db, tenant_id, "pp-work-default")
    work = await create_project(ProjectCreate(name="Рабочий по умолчанию"), owner, db)
    stages = await seed_stages(db, work.id, owner, names=("Первая", "Вторая"))
    await db.commit()

    task = await create_task(work.id, TaskCreate(title="Рабочая"), owner, db)
    await db.commit()
    assert task.stage_id == stages[0].id


async def test_stageless_tasks_get_distinct_positions(db, tenant_id):
    """У «без статуса» своя очередь позиций — иначе порядок списка случаен."""
    owner = await _member(db, tenant_id, "pp-positions")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    first = await create_task(personal_id, TaskCreate(title="Первая"), owner, db)
    second = await create_task(personal_id, TaskCreate(title="Вторая"), owner, db)
    await db.commit()
    assert first.position != second.position
    assert second.position > first.position


# ─── Исполнитель личной задачи ──────────────────────────────────────────────


async def test_personal_task_assigns_owner(db, tenant_id):
    """Задача «на себя»: владелец личного — сразу исполнитель.

    Без этого личная задача оставалась ничьей: пустой стек аватаров в строке
    и промах фильтра «Исполнитель».
    """
    owner = await _member(db, tenant_id, "pp-selfassign")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    task = await create_task(personal_id, TaskCreate(title="Купить хлеб"), owner, db)
    await db.commit()
    assert [a.employee_id for a in task.assignees] == [owner.employee_id]

    # Задача-инструкция заводится тем же путём.
    guide_assignees = (
        await db.execute(
            select(TaskAssignee.employee_id)
            .join(Task, Task.id == TaskAssignee.task_id)
            .where(Task.project_id == personal_id, Task.title == GUIDE_TASK_TITLE)
        )
    ).scalars().all()
    assert list(guide_assignees) == [owner.employee_id]


async def test_personal_task_respects_explicit_empty_assignees(db, tenant_id):
    """Пустой список — ЯВНОЕ «никого», его не перебиваем.

    `resolve_assignee_ids` различает «поля нет» (None) и «снять всех» ([]);
    авто-назначение работает только на первом.
    """
    owner = await _member(db, tenant_id, "pp-noassign")
    personal_id = await ensure_personal_project(db, owner)
    await db.commit()

    task = await create_task(
        personal_id, TaskCreate(title="Ничья", assignee_ids=[]), owner, db
    )
    await db.commit()
    assert task.assignees == []


async def test_work_task_stays_unassigned(db, tenant_id):
    """Регресс: в обычном проекте создатель исполнителем НЕ становится."""
    owner = await _member(db, tenant_id, "pp-work-assign")
    work = await create_project(ProjectCreate(name="Рабочий без исполнителя"), owner, db)
    await db.commit()

    task = await create_task(work.id, TaskCreate(title="Рабочая"), owner, db)
    await db.commit()
    assert task.assignees == []


async def test_admin_in_foreign_personal_does_not_self_assign(db, tenant_id):
    """В ЧУЖОМ личном пространстве авто-назначения нет.

    Точечный доступ hub-admin по прямой ссылке сохранён (0042), но задача,
    заведённая им у сотрудника, не должна становиться задачей админа.
    """
    owner = await _member(db, tenant_id, "pp-foreign-owner")
    personal_id = await ensure_personal_project(db, owner)
    admin = await _member(db, tenant_id, "pp-foreign-admin", role="admin")
    await db.commit()

    task = await create_task(personal_id, TaskCreate(title="Чужая"), admin, db)
    await db.commit()
    assert task.assignees == []
