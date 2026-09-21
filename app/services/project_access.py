"""Per-project RBAC helpers.

In-app roles (`owner | editor | viewer`) live in `project_members.role` —
they're NOT in the JWT. JWT-level role is `hub:admin | member | viewer`:
- `hub:admin` — superuser inside the tenant, bypasses per-project checks.
- `hub:member` — in-app role decides; создавать проекты/папки может ТОЛЬКО
  member с активным learn-профилем `org_role ∈ PROJECT_CREATOR_ORG_ROLES`
  (офис, ТУ, франчайзи) — линейный сотрудник на точке проекты не заводит
  (решение владельца 2026-08-21, QA-0821 #21).
- `hub:viewer` — read-only, can't create projects.

API:
    is_hub_admin(principal) -> bool
    can_create_project(db, principal) -> bool      (async — смотрит профиль)
    can_manage_project_folders(db, principal) -> bool
    fetch_project_or_404(db, project_id) -> Project
    get_my_role(db, project_id, employee_id) -> ProjectRole | None
    require_project_role(
        db, project_id, principal, *, allow=("owner",)
    ) -> tuple[Project, ProjectRole]
        → raises 404 if not visible, 403 if visible but role not in allow.
    capabilities(principal, my_role) -> (can_edit, can_manage)
        → эффективные права для UI; считаются ТОЛЬКО здесь.

Шаблоны проектов (0060) живут по СВОИМ правилам, и они тоже здесь:
    can_view_templates(db, principal) — видеть и использовать шаблоны
        (= право создавать проекты);
    can_edit_template(principal, created_by) — править: автор и hub-admin;
    template_role(principal, project) — синтезированная роль вместо ростера;
    open_template_scope(db, principal, …) — открыть область шаблона в сессии.
Роли из `project_members` шаблона доступа НЕ дают: ростер шаблона — это
состав будущих проектов, а не список тех, кто правит шаблон.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import set_template_scope
from app.models.employee_profile import EmployeeProfile
from app.models.project import Project, ProjectMember

ProjectRole = Literal["owner", "editor", "viewer"]
HUB_ADMIN_ROLE = "admin"
# org_role learn-профиля, которым разрешено создавать проекты и управлять
# папками (кроме hub:admin). Линейный `employee` — нет.
PROJECT_CREATOR_ORG_ROLES: frozenset[str] = frozenset({"office", "tu", "franchisee_owner"})
CREATE_PROJECT_DENIED = (
    "Создавать проекты могут администраторы Hub и сотрудники офиса, ТУ и "
    "франчайзи — обратитесь к администратору"
)

# Две ступени прав. Держим их РЯДОМ с require_project_role: списки обязаны
# совпадать с `allow=` в ручках, иначе UI снова разъедется с бэкендом.
#
# `EDIT_ROLES` — это ровно то, что клиенту обещает `ProjectResponse.can_edit`
# (см. capabilities ниже). Поэтому ручки профиля проекта берут КОНСТАНТУ, а не
# литерал: гейт и флаг обязаны быть одним предикатом, иначе экран «О проекте»
# нарисует поля и получит 403. Связаны `app/api/projects.py`: PATCH
# /projects/{id}, PUT /projects/{id}/badge, POST /projects/{id}/badge/image.
#
# Литералами `("owner", "editor")` осознанно оставлены пять call-site'ов, где
# ступень совпала случайно, а не по смыслу: `tasks_import.py`, `stages.py`
# (три ручки) и создание задачи в `tasks.py`. Это не недосмотр — сметать их
# под константу стоит отдельной правкой, вместе с решением, что именно
# «edit-tier» означает для задач.
EDIT_ROLES: tuple[ProjectRole, ...] = ("owner", "editor")
MANAGE_ROLES: tuple[ProjectRole, ...] = ("owner",)

TEMPLATE_EDIT_DENIED = "Шаблон правят его автор и администраторы Hub"
TemplateMode = Literal["view", "edit"]
_CAN_VIEW_TEMPLATES_KEY = "can_view_templates"


def is_hub_admin(principal: Principal) -> bool:
    return principal.role_for("hub") == HUB_ADMIN_ROLE


async def can_create_project(db: AsyncSession, principal: Principal) -> bool:
    """admin — всегда; member — только с активным профилем офис/ТУ/франчайзи.

    Профиль ищется по `employee_id` (как `org_scope.resolve_scope`); у member
    без профиля (API-клиент, не заходивший в UI — `/api/me` связывает профиль
    по email при первом входе) — False. hub:viewer — всегда False.
    """
    role = principal.role_for("hub")
    if role == HUB_ADMIN_ROLE:
        return True
    if role != "member":
        return False
    row = await db.execute(
        select(EmployeeProfile.org_role).where(
            EmployeeProfile.employee_id == principal.employee_id,
            EmployeeProfile.status == "active",
        )
    )
    org_role = row.scalars().first()
    return org_role in PROJECT_CREATOR_ORG_ROLES


async def can_manage_project_folders(db: AsyncSession, principal: Principal) -> bool:
    """Папки ОБЩИЕ для тенанта, поэтому гейт — тот же, что у создания проекта:
    равный blast-radius, hub:viewer и линейный сотрудник остаются read-only.

    Не admin-only сознательно: ОС ровно про то, что в плоском списке тонут
    обычные пользователи — если раскладывать может только админ, фича мертва
    в тенанте с одним админом. Не project-owner: у папки нет владельца, гейт
    по роли в конкретном проекте не выразим.

    Сужение до is_hub_admin — правка ровно здесь, в одном месте.
    """
    return await can_create_project(db, principal)


def capabilities(
    principal: Principal, my_role: ProjectRole | None
) -> tuple[bool, bool]:
    """(can_edit, can_manage) — что вызывающий РЕАЛЬНО может в этом проекте.

    Отдаётся клиенту в ProjectResponse, чтобы фронт не заводил свою копию
    правила: раньше он её завёл, не знал про hub:admin-байпас ниже в
    require_project_role и показывал админу вне членства проект read-only,
    хотя запись сервером разрешена.
    """
    if is_hub_admin(principal):
        return True, True
    return my_role in EDIT_ROLES, my_role in MANAGE_ROLES


async def can_view_templates(db: AsyncSession, principal: Principal) -> bool:
    """Видеть и использовать шаблоны — тем, кто может создавать проекты.

    Кэш в `db.info`: зависимость страницы шаблона и библиотека зовут проверку
    на каждом запросе, а она ходит в `employee_profiles`.
    """
    cached = db.info.get(_CAN_VIEW_TEMPLATES_KEY)
    if cached is None:
        cached = await can_create_project(db, principal)
        db.info[_CAN_VIEW_TEMPLATES_KEY] = cached
    return bool(cached)


def can_edit_template(principal: Principal, created_by: UUID) -> bool:
    """Править шаблон — автор и hub-admin (решение владельца 21.09)."""
    return is_hub_admin(principal) or created_by == principal.employee_id


def template_role(principal: Principal, project: Project) -> ProjectRole | None:
    """Роль в шаблоне — синтезированная, ростер не читается.

    hub-admin → None (обход, как в `require_project_role`), автор → owner,
    остальные видящие → viewer. Без этого сотрудник офиса с ролью editor в
    СОСТАВЕ шаблона (состав = будущие участники проектов) правил бы чужой
    шаблон.
    """
    if is_hub_admin(principal):
        return None
    return "owner" if project.created_by == principal.employee_id else "viewer"


async def open_template_scope(
    db: AsyncSession,
    principal: Principal,
    *,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    mode: TemplateMode = "view",
) -> UUID | None:
    """Если объект — шаблон и человеку можно, открыть его область в сессии.

    Возвращает id шаблона или None. «Не шаблон», «модуль выключен» и «нельзя
    видеть шаблоны» — одинаково None без исключения: область остаётся
    закрытой, и ручка сама ответит своим обычным 404 (существование шаблона
    не раскрываем). `mode="edit"` для не-автора — 403.

    Права проверяются ДО того, как строки шаблона попадут в сессию: зонд
    `app_template_lookup` (SECURITY DEFINER, 0060) отдаёт только id и автора.
    """
    if project_id is None and task_id is None:
        return None
    row = (
        await db.execute(
            text("SELECT project_id, created_by FROM app_template_lookup(:p, :t)"),
            {"p": project_id, "t": task_id},
        )
    ).first()
    if row is None:
        return None
    template_id, created_by = row

    from app.services.project_templates.gate import templates_enabled_for

    if not await templates_enabled_for(db, principal.tenant_id):
        return None
    if not await can_view_templates(db, principal):
        return None
    if mode == "edit" and not can_edit_template(principal, created_by):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TEMPLATE_EDIT_DENIED)
    await set_template_scope(db, str(template_id))
    return template_id


async def open_template_if_hidden(
    db: AsyncSession,
    principal: Principal,
    *,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    mode: TemplateMode,
) -> None:
    """Лениво открыть область, если объект не виден: сначала обычный `db.get`.

    Нашёлся — живой (или уже видимый) объект лежит в identity map, и ручка
    возьмёт его оттуда без лишнего запроса; зонд зовётся только при промахе.
    Общая точка для `deps.get_db_template_page` и ручек, где id шаблона не в
    пути (колонка по `stage_id`, вложение по `attachment_id`, загрузка с
    `task_id` полем формы).
    """
    from app.models.task import Task

    if project_id is not None:
        if await db.get(Project, project_id) is not None:
            return
        await open_template_scope(db, principal, project_id=project_id, mode=mode)
    elif task_id is not None:
        if await db.get(Task, task_id) is not None:
            return
        await open_template_scope(db, principal, task_id=task_id, mode=mode)


async def fetch_project_or_404(db: AsyncSession, project_id: UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return project


async def get_my_role(
    db: AsyncSession, project_id: UUID, employee_id: UUID
) -> ProjectRole | None:
    row = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.employee_id == employee_id,
        )
    )
    return row.scalar_one_or_none()  # type: ignore[return-value]


async def ensure_project_member(
    db: AsyncSession,
    *,
    project_id: UUID,
    tenant_id: UUID,
    employee_id: UUID,
    role: ProjectRole = "viewer",
    added_by: UUID | None = None,
) -> None:
    """Идемпотентное членство (авто-viewer при назначении исполнителем).

    INSERT ... ON CONFLICT DO NOTHING по (project_id, employee_id) —
    существующая роль НИКОГДА не понижается и не повышается; race-safe
    (тот же паттерн, что _ensure_watcher в tasks.py). Снятие assignee
    членство не удаляет — вызывающие просто не зовут ничего обратного.

    В ШАБЛОНЕ ничего не делает (0060): состав шаблона — это будущие
    участники проектов из него, и он меняется только явно, на вкладке
    «Участники». Иначе каждый, кого однажды назначили и потом сняли, стал бы
    участником всех будущих проектов (членство при снятии не отзывается), а
    копирование и так выдаёт viewer всем исполнителям и наблюдателям.
    """
    project = await db.get(Project, project_id)
    if project is not None and project.is_template:
        return
    await db.execute(
        pg_insert(ProjectMember)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            employee_id=employee_id,
            role=role,
            added_by=added_by,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "employee_id"])
    )


async def require_project_role(
    db: AsyncSession,
    project_id: UUID,
    principal: Principal,
    *,
    allow: tuple[ProjectRole, ...] = ("owner", "editor", "viewer"),
) -> tuple[Project, ProjectRole | None]:
    """Return the project + caller's role. 404 if invisible, 403 if not enough role.

    `hub:admin` always passes the role check (returns role=None to signal admin
    bypass). For everyone else: must be a project_members entry with role ∈ allow.
    """
    project = await fetch_project_or_404(db, project_id)
    if project.is_template:
        # Видимый шаблон = область уже открыта `open_template_scope`, а она
        # проверила и рубильник, и право видеть. Роль — синтезированная.
        role = template_role(principal, project)
        if role is not None and role not in allow:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=TEMPLATE_EDIT_DENIED
            )
        return project, role
    if is_hub_admin(principal):
        return project, None

    my_role = await get_my_role(db, project_id, principal.employee_id)
    if my_role is None:
        # Hide existence from non-members.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    if my_role not in allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Требуется роль {'/'.join(allow)} в проекте",
        )
    return project, my_role
