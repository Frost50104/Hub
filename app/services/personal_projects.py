"""Личное пространство сотрудника: персональный проект «Личное».

Инварианты:
- ровно один на (tenant_id, employee_id) — держит partial UNIQUE
  `uq_projects_personal_owner`, а НЕ приложенческий лок;
- проект НЕ показывается ни в одном списке проектов — ни владельцу, ни
  hub-admin: вход в фичу — секция «ЛИЧНОЕ» на /my. Скрытие СЕРВЕРНОЕ:
  клиентский фильтр не сработал бы у застрявших PWA-бандлов;
- точечный доступ по прямой ссылке у hub-admin сохраняется (админ-байпас
  `require_project_role` не трогаем), но МАССОВЫЕ выборки — поиск, комментарии,
  инструменты ассистента — чужие личные задачи не возвращают: иначе личные
  заметки сотрудников уезжают во внешнюю LLM;
- участники разрешены, но приглашённый видит ТОЛЬКО свои задачи этого проекта
  (`personal_task_scope`) — назначение исполнителя даёт viewer-членство
  (`project_access.ensure_project_member`), а оно открывало бы весь список;
- гейт `can_create_project` сознательно обойдён: личное есть у каждого с
  hub-ролью, включая линейного `employee` и `hub:viewer`;
- нельзя архивировать, класть в папку и публиковать ссылкой
  (`assert_not_personal`).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from signaris_auth import Principal
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task, TaskAssignee, TaskWatcher
from app.services.onboarding import create_guide_task
from app.services.project_access import is_hub_admin, require_project_role
from app.services.projects import create_project_record

log = structlog.get_logger(__name__)

PERSONAL_PROJECT_NAME = "Личное"
# Транслит «ЛИЧНОЕ» (project_key._CYRILLIC_MAP). Задан явно, а не через
# generate_unique_key: та для «Личное» в обычном регистре даёт «L» — строчные
# буквы в карте транслита отсутствуют. Суффикс ТОЛЬКО цифровой:
# `_TASK_KEY_RE` ассистента (assistant/context.py) — [A-Za-zА-Яа-я0-9]{1,16},
# и «LICNOE_3F9A-5» перестал бы резолвиться в resolve_task.
PERSONAL_KEY_BASE = "LICNOE"
_KEY_MAX_SUFFIX = 100_000
_CREATE_ATTEMPTS = 3


# ─── Предикаты видимости ────────────────────────────────────────────────────
# Живут в одном месте, чтобы правило не расползлось: любой НОВЫЙ кросс-проектный
# список обязан применить один из них (реестр мест — в докстрингах вызовов).


def not_personal() -> ColumnElement[bool]:
    """«Проект не личный» — для СПИСКОВ ПРОЕКТОВ (сайдбар, /projects, поиск)."""
    return Project.personal_owner_id.is_(None)


def personal_visible_to(employee_id: UUID) -> ColumnElement[bool]:
    """«не личный ИЛИ мой личный» — для кросс-проектных выборок ЗАДАЧ.

    Применяется ДО ветки hub-admin: точечный доступ админа остаётся, но
    выгребать чужое личное пачкой (поиск, ассистент) он не должен.
    """
    return or_(
        Project.personal_owner_id.is_(None),
        Project.personal_owner_id == employee_id,
    )


def not_my_personal(employee_id: UUID) -> ColumnElement[bool]:
    """«не мой личный» — для GET /me/tasks.

    `is_distinct_from`, а НЕ `!=`: для обычного проекта `NULL != :id` даёт NULL,
    и WHERE отсеял бы ВСЕ рабочие задачи, оставив только чужие личные.
    """
    return Project.personal_owner_id.is_distinct_from(employee_id)


# ─── Чтение и создание ──────────────────────────────────────────────────────


async def get_personal_project_id(db: AsyncSession, employee_id: UUID) -> UUID | None:
    """Один индексный SELECT по `uq_projects_personal_owner`."""
    return (
        await db.execute(
            select(Project.id).where(Project.personal_owner_id == employee_id)
        )
    ).scalar_one_or_none()


async def allocate_personal_key(db: AsyncSession) -> str:
    """LICNOE / LICNOE2 / … — первый свободный ключ в тенанте.

    Не `generate_unique_key`: её cap `range(2, 1000)` рассчитан на
    «патологический ввод», а здесь упирается в ЧИСЛЕННОСТЬ тенанта — в сети на
    1000+ сотрудников автосоздание начало бы падать.

    `tenant_id` вручную не фильтруем — это делает RLS.
    """
    rows = await db.execute(
        select(Project.key).where(Project.key.like(f"{PERSONAL_KEY_BASE}%"))
    )
    used = {row[0] for row in rows.all()}
    if PERSONAL_KEY_BASE not in used:
        return PERSONAL_KEY_BASE
    for i in range(2, _KEY_MAX_SUFFIX):
        candidate = f"{PERSONAL_KEY_BASE}{i}"
        if candidate not in used:
            return candidate
    raise RuntimeError("personal key space exhausted")


async def ensure_personal_project(
    db: AsyncSession, principal: Principal
) -> UUID | None:
    """Id личного проекта; создаёт при первом входе. БЕЗ commit'а.

    None — у principal нет hub-роли (юзер другого продукта Signaris) ИЛИ проект
    не удалось создать. Исключение наружу НЕ выпускаем: единственный вызывающий
    — `GET /api/me`, вход в приложение, и падение там отрезало бы человека и от
    трекера, и от обучения. Деградация — «фичи нет», а не «Hub не работает».
    """
    if principal.role_for("hub") is None:
        return None

    existing = await get_personal_project_id(db, principal.employee_id)
    if existing is not None:
        return existing

    for _ in range(_CREATE_ATTEMPTS):
        try:
            key = await allocate_personal_key(db)
            # SAVEPOINT обязателен: без него IntegrityError аборти́т ВСЮ
            # транзакцию /api/me вместе с ensure_profile_for_principal, и
            # пользователь останется без learn-профиля. Ручка create_project
            # может позволить себе db.rollback() + 409, ensure — нет.
            async with db.begin_nested():
                project = await create_project_record(
                    db,
                    tenant_id=principal.tenant_id,
                    created_by=principal.employee_id,
                    name=PERSONAL_PROJECT_NAME,
                    key=key,
                    personal_owner_id=principal.employee_id,
                )
            # Первый вход = момент создания личного проекта (партиальный
            # UNIQUE делает его однократным), поэтому задача-инструкция
            # заводится здесь и отдельного флага «уже показывали» не требует.
            # Ветку гонки ниже НЕ трогаем: там всё создал победитель.
            await create_guide_task(db, principal=principal, project_id=project.id)
            return project.id
        except IntegrityError:
            # Откат SAVEPOINT'а выбрасывает из сессии объекты, УСПЕВШИЕ
            # флашнуться внутри него, но не те, что остались pending (сессия
            # autoflush=False) — иначе следующий flush повторил бы INSERT.
            # Точечно, а не expunge_all(): чужую работу в сессии не трогаем.
            for pending in list(db.new):
                db.expunge(pending)
            # Гонка по uq_projects_personal_owner: параллельный /api/me успел
            # первым (наш INSERT ждал на индексе его commit'а) — берём его.
            winner = await get_personal_project_id(db, principal.employee_id)
            if winner is not None:
                return winner
            # Иначе конфликт по uq_projects_tenant_key с ДРУГИМ сотрудником,
            # выбравшим тот же ключ, — пробуем следующий.
        except RuntimeError:
            break

    log.warning(
        "personal_project.create_failed", employee_id=str(principal.employee_id)
    )
    return None


# ─── Инварианты ─────────────────────────────────────────────────────────────


def assert_not_personal(project: Project, *, action: str) -> None:
    """409 на операции, которые ломают личное пространство.

    Архивация: архивный личный исчезнет из своей же секции, а `list_projects`
    его не покажет — «Разархивировать» нажать будет негде.
    Папка: раскладка общая, а `project_count` клиент считает из `useProjects()`,
    где личных нет. Публичная ссылка scope=project отдаёт анонимам весь список
    задач.
    """
    if project.personal_owner_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Личный проект нельзя {action}",
        )


def personal_task_scope(
    project: Project, principal: Principal
) -> ColumnElement[bool] | None:
    """Ограничение выборки задач внутри ЧУЖОГО личного проекта.

    None — доступ полный: обычный проект, свой личный или hub-admin. Иначе —
    «я исполнитель ИЛИ наблюдатель»: приглашённый на одну задачу не должен
    читать весь личный список (viewer-членство ему выдаёт `ensure_project_member`
    при назначении).
    """
    owner_id = project.personal_owner_id
    if owner_id is None or owner_id == principal.employee_id:
        return None
    if is_hub_admin(principal):
        return None
    me = principal.employee_id
    return or_(
        select(TaskAssignee.task_id)
        .where(TaskAssignee.task_id == Task.id, TaskAssignee.employee_id == me)
        .exists(),
        select(TaskWatcher.task_id)
        .where(TaskWatcher.task_id == Task.id, TaskWatcher.employee_id == me)
        .exists(),
    )


def assert_full_project_access(project: Project, principal: Principal) -> None:
    """403 приглашённому на агрегатах ЧУЖОГО личного проекта.

    Дашборд, календарь и хронология считают по ВСЕМ задачам проекта — точечно
    отфильтровать их до «моих» нельзя так, чтобы цифры оставались осмысленными,
    а приглашённому на одну задачу они и не нужны.
    """
    if personal_task_scope(project, principal) is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступны только назначенные вам задачи этого проекта",
        )


async def assert_task_visible(
    db: AsyncSession, task: Task, project: Project, principal: Principal
) -> None:
    """404 на чужую личную задачу, к которой вызывающий не причастен.

    404, а не 403 — существование скрываем, как `require_project_role` скрывает
    чужой проект.
    """
    scope = personal_task_scope(project, principal)
    if scope is None:
        return
    visible = (
        await db.execute(select(Task.id).where(Task.id == task.id, scope))
    ).scalar_one_or_none()
    if visible is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )


async def require_task_access(
    db: AsyncSession,
    task: Task,
    principal: Principal,
    *,
    allow: tuple[str, ...] = ("owner", "editor", "viewer"),
) -> tuple[Project, str | None]:
    """`require_project_role` + фильтр личного проекта.

    Замена всех вызовов вида `require_project_role(db, task.project_id, …)`:
    иначе суб-ресурсы задачи (комментарии, вложения, активность) обходили бы
    ограничение `personal_task_scope`.
    """
    project, role = await require_project_role(
        db, task.project_id, principal, allow=allow  # type: ignore[arg-type]
    )
    await assert_task_visible(db, task, project, principal)
    return project, role
