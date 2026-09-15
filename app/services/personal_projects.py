"""Личное пространство сотрудника: персональный проект «Личное».

Инварианты:
- ровно один на (tenant_id, employee_id) — держит partial UNIQUE
  `uq_projects_personal_owner`, а НЕ приложенческий лок;
- проект НЕ показывается ни в одном списке проектов — ни владельцу, ни
  hub-admin: вход в фичу — секция «ЛИЧНОЕ» на /my. Скрытие СЕРВЕРНОЕ:
  клиентский фильтр не сработал бы у застрявших PWA-бандлов;
- hub-admin правила НЕ обходит (решение владельца 15.09): в чужом личном он
  такой же гость — видит только задачи, где он исполнитель или наблюдатель.
  Прежде у него был точечный доступ по прямой ссылке; владелец, увидев под
  своей учёткой чужие заметки, сказал прямо: «я не должен видеть её личные
  задачи, где я не участник». МАССОВЫЕ выборки — поиск, комментарии,
  инструменты ассистента — чужие личные задачи не возвращали и раньше: иначе
  личные заметки сотрудников уезжают во внешнюю LLM;
- участники разрешены, но приглашённый видит ТОЛЬКО свои задачи этого проекта
  (`personal_task_scope`) — назначение исполнителя даёт viewer-членство
  (`project_access.ensure_project_member`), а оно открывало бы весь список.
  Это правило распространяется и на МЕТАДАННЫЕ проекта (16.09): метки, колонки
  со счётчиками и определения кастом-полей гостю отдаются ПУСТЫМИ
  (`is_foreign_personal` — их зовёт карточка задачи, и 403 дал бы там тост
  вместо тихой деградации), а значения полей всех задач и состав участников —
  403 (`assert_full_project_access`), как остальные агрегаты. До правки эти
  пять ручек стояли на голом `require_project_role` и утверждение выше было
  неверным: гость по одному поручению читал метки владельца, его колонки и
  список всех, кому тот что-то поручал;
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
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember
from app.models.task import Task, TaskAssignee, TaskWatcher
from app.services.project_access import require_project_role
from app.services.project_key import _FALLBACK, _candidate, generate_unique_key
from app.services.projects import create_project_record

log = structlog.get_logger(__name__)

# Имя одно на всех (16.09): личный проект перестал быть «Личным» сбоку от
# «Моих задач» — он и ЕСТЬ «Мои задачи», экран открывает его, а не соседнюю
# надстройку. Чужому личному это имя подменяется в ответе на «Личное · Имя»
# (`personal_display_name`): гость читал бы «Мои задачи» как свои.
PERSONAL_PROJECT_NAME = "Мои задачи"
# Запасной ключ, когда из ФИО не собрать ничего пригодного (пустое имя, одни
# цифры). Значение историческое — так назывались ВСЕ личные проекты до 16.09;
# держим его константой, а не пересчитываем из слова «Личное»: карта
# транслитерации с тех пор получила диграфы и дала бы «LICHNOE», то есть
# третий формат ключа на ровном месте.
PERSONAL_KEY_BASE = "LICNOE"
# Потолок БАЗЫ ключа. 13, а не 16: `_TASK_KEY_RE` ассистента
# (`assistant/context.py`) разрешает [A-Za-zА-Яа-я0-9]{1,16} на ключ ЦЕЛИКОМ, а
# суффикс коллизии клеится после среза — «KORABLESTROITELE2» уже не резолвится
# в `resolve_task`. 13 + до трёх цифр = ровно 16. Суффикс только цифровой: `_`
# и `-` внутри ключа та же регулярка не принимает.
PERSONAL_KEY_MAX_LEN = 13
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

    Применяется ДО ветки hub-admin — и это было верно ещё когда у админа был
    точечный доступ по ссылке: выгребать чужое личное пачкой (поиск, ассистент)
    он не должен был никогда. С 15.09 админ не обходит и точечную проверку
    (`personal_task_scope`).
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


def personal_key_base(full_name: str | None) -> str:
    """«Пётр Попов» → `PETRPOPOV`: основа ключа личного проекта.

    Берём ОБА слова, а не первое. Замер на 178 живых владельцах: первое слово
    даёт 123 уникальных ключа из 178 (83 проекта с цифрой), оба — 171 (13 с
    цифрой). Причина в данных: порядок слов в справочнике смешанный — у 139
    человек фамилия вторым словом, у 70 первым (`services/people_search.py`),
    поэтому «первое слово» через раз оказывается именем, и получается
    `ANASTASIY`, `ANASTASIY2` … `ANASTASIY7` — тот же `LICNOE26` в профиль.

    Третье и дальше слова отбрасываем: отчество ключ только удлиняет, а
    потолок 13 символов жёсткий.

    Собрать из ФИО именно ФАМИЛИЮ нельзя в принципе — структурированного поля
    нет ни в `shadow_users`, ни в `employee_profiles`. Приёмка разовой джобы
    поэтому ручная, по отчёту dry-run.

    Ничего пригодного (пустое имя, одни цифры, служебная строка) → `LICNOE`,
    то есть прежнее поведение.
    """
    words = (full_name or "").split()[:2]
    base = _candidate(" ".join(words) if len(words) < 2 else "".join(words),
                      max_len=PERSONAL_KEY_MAX_LEN)
    return PERSONAL_KEY_BASE if base == _FALLBACK else base


async def allocate_personal_key(
    db: AsyncSession, *, owner_name: str | None, tenant_id: UUID
) -> str:
    """`PETRPOPOV` / `PETRPOPOV2` / … — первый свободный ключ в тенанте.

    До 16.09 база была ОДНА на весь тенант (`LICNOE`, `LICNOE2`…), и свой
    аллокатор существовал ровно поэтому: cap `generate_unique_key` в 999
    упирался бы не в «патологический ввод», а в численность компании. С базой
    из ФИО коллизии — это только тёзки (на проде 4 группы), так что общий
    генератор подходит и второй реализации перебора суффиксов быть не должно.

    Ключи личных и обычных проектов живут в ОДНОМ namespace
    (`UNIQUE(tenant_id, key)`), и `generate_unique_key` проверяет весь тенант —
    занятый рабочим проектом `POPOV` уведёт личный в `POPOV2`.
    """
    return await generate_unique_key(
        db,
        name=personal_key_base(owner_name),
        tenant_id=tenant_id,
        max_len=PERSONAL_KEY_MAX_LEN,
    )


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
            key = await allocate_personal_key(
                db,
                owner_name=principal.full_name,
                tenant_id=principal.tenant_id,
            )
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
            # Импорт внутри функции: онбординг знает про задачи, задачи —
            # про личное пространство, и модульный импорт замкнул бы кольцо
            # `personal_projects → onboarding → tasks → personal_projects`.
            # Развязываем в перевёрнутой зависимости: создание проекта не
            # обязано знать про содержимое первой задачи.
            from app.services.onboarding import create_guide_task

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
        except (RuntimeError, ValueError):
            # ValueError — из `generate_unique_key`, когда исчерпаны суффиксы
            # (999 тёзок). Ловить ОБА типа обязательно: единственный вызывающий
            # — `GET /api/me`, то есть ВХОД в приложение, и исключение отсюда
            # уронило бы его целиком. Деградация здесь — «личного пространства
            # нет», а не «Hub не работает» (докстринг ручки обещает именно это).
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


def my_task_scope(employee_id: UUID) -> ColumnElement[bool]:
    """«Моё» для кросс-проектных списков: назначено мне ИЛИ лежит в моём личном.

    Вторая ветка — КОРРЕЛИРОВАННЫЙ EXISTS, а не `Project.personal_owner_id ==
    employee_id`, хотя во втором варианте она короче. Прямое сравнение требует
    джойна на `projects` в КАЖДОМ запросе, куда предикат попадёт, а молча
    требовать джойн нельзя: `my_daily_stmt` и `my_created_stmt` в `/me/stats`
    его не делают, и SQLAlchemy на прямом сравнении добавляет `projects` в
    FROM декартовым произведением (предупреждение «cartesian product», цифры
    умножаются на число проектов). Предикат обязан быть самодостаточным — его
    подставляют в четыре разных запроса.

    Вторая ветка не косметика. С 16.09 `/my` — единственный вход в личное
    пространство, а задача там может остаться без исполнителей: снять их
    явным пустым списком разрешено (`test_personal_task_respects_explicit_
    empty_assignees`), и `apply_personal_assignee_rules` на пустом наборе
    ничего не делает. На одном `assignee_exists` такая задача исчезла бы с
    экрана совсем — раньше её показывала секция «ЛИЧНОЕ» через ручку проекта.

    Предикат ОБЩИЙ для `/me/tasks` и `/me/stats::_mine`: разойдутся — снова
    получим «цифра на Главной не сходится со списком под ней».
    """
    return or_(
        select(TaskAssignee.task_id)
        .where(TaskAssignee.task_id == Task.id, TaskAssignee.employee_id == employee_id)
        .correlate(Task)
        .exists(),
        select(Project.id)
        .where(Project.id == Task.project_id, Project.personal_owner_id == employee_id)
        # `correlate(Task)` обязателен: в `/me/tasks` внешний запрос джойнит и
        # `tasks`, и `projects`, авто-корреляция забрала бы обе таблицы, и у
        # подзапроса не осталось бы FROM вовсе (InvalidRequestError). Явная
        # корреляция ровно по `tasks` делает предикат пригодным и там, где
        # `projects` во внешнем запросе есть, и там, где его нет.
        .correlate(Task)
        .exists(),
    )


def personal_list_scope(employee_id: UUID) -> ColumnElement[bool]:
    """Кросс-проектный двойник `personal_task_scope` — для выборок ПО АВТОРУ.

    Держит две вещи разом:

    1. **Я всё ещё участник проекта.** `/me/tasks` членство не проверяет вовсе
       (там только `assignee_exists`), и задача из проекта, откуда меня убрали,
       остаётся в списке, а карточка отвечает 404. Повторять эту ошибку в новой
       ручке нельзя: строка, которая не открывается, хуже отсутствующей.
    2. **В ЧУЖОМ личном — только то, к чему я причастен** (исполнитель или
       наблюдатель), то есть ровно правило `personal_task_scope`.

    **Ветки hub-admin здесь НЕТ, и это не упущение.** `require_project_role`
    админа мимо членства пропускает, а `personal_task_scope` с 15.09 — нет:
    админ, заведший задачу в чьём-то личном и не ставший участником, получил бы
    строку в списке и 404 при клике по ней.
    """
    involved = or_(
        select(TaskAssignee.task_id)
        .where(TaskAssignee.task_id == Task.id, TaskAssignee.employee_id == employee_id)
        .correlate(Task)
        .exists(),
        select(TaskWatcher.task_id)
        .where(TaskWatcher.task_id == Task.id, TaskWatcher.employee_id == employee_id)
        .correlate(Task)
        .exists(),
    )
    return and_(
        select(ProjectMember.project_id)
        .where(
            ProjectMember.project_id == Project.id,
            ProjectMember.employee_id == employee_id,
        )
        # Корреляция по `projects`: подзапрос про проект, а не про задачу.
        .correlate(Project)
        .exists(),
        or_(
            Project.personal_owner_id.is_(None),
            Project.personal_owner_id == employee_id,
            involved,
        ),
    )


def personal_task_scope(
    project: Project, principal: Principal
) -> ColumnElement[bool] | None:
    """Ограничение выборки задач внутри ЧУЖОГО личного проекта.

    None — доступ полный: обычный проект или свой личный. Иначе — «я
    исполнитель ИЛИ наблюдатель»: приглашённый на одну задачу не должен читать
    весь личный список (viewer-членство ему выдаёт `ensure_project_member` при
    назначении).

    **hub-admin правила НЕ обходит (решение владельца 15.09).** До этого у него
    был точечный доступ по прямой ссылке — «разобраться, когда человек просит
    помочь». Владелец, зайдя под своей админской учёткой, увидел в чужом личном
    проекте чужие заметки и сказал прямо: «я не должен видеть её личные задачи,
    где я не участник». Личное пространство перестало быть личным ровно в тот
    момент, когда у кого-то в продукте есть ключ от него.

    Это согласуется с остальной защитой: `personal_visible_to` (поиск,
    комментарии, инструменты ассистента) админа не пропускал никогда — он
    применяется ДО ветки админа. Теперь то же самое и на точечном доступе.

    Что админ теряет: открыть чужую личную задачу по ссылке он больше не может
    (404), агрегаты чужого личного — 403. Чтобы помочь человеку с его личной
    задачей, надо оказаться в ней исполнителем или наблюдателем — то есть
    человек должен позвать сам.
    """
    owner_id = project.personal_owner_id
    if owner_id is None or owner_id == principal.employee_id:
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


def may_edit_delegated(task: Task, project: Project, principal: Principal) -> bool:
    """Автор ПОРУЧЕННОЙ задачи правит и удаляет её, хоть и viewer в чужом личном.

    Правило узкое и живёт в ручках задачи (как `ASSIGNEE_EDITABLE_FIELDS`), а
    НЕ в `require_task_access`: тот охраняет приватность личного пространства
    целиком, и послабление в нём открыло бы гостю чужие заметки.

    Зачем вообще: поручение (`POST /api/me/delegate`) даёт автору viewer —
    этого хватает, чтобы видеть и комментировать, но не хватает, чтобы
    исправить опечатку или ОТОЗВАТЬ задачу из чужого inbox'а. Без правила
    получался тупик: написал не тому — и сделать ничего нельзя.

    Чистая функция без запросов: и `task`, и `project` у ручек уже в руках.
    """
    owner_id = project.personal_owner_id
    return (
        owner_id is not None
        and owner_id != principal.employee_id
        and task.created_by == principal.employee_id
    )


def is_foreign_personal(project: Project, principal: Principal) -> bool:
    """«Это ЧУЖОЕ личное пространство, и я в нём гость».

    Обёртка над `personal_task_scope` для ручек, которым скоуп применить не к
    чему: у меток, колонок и определений кастом-полей нет столбца «чья задача»,
    поэтому урезать их нечем — гостю они отдаются пустыми.

    Пустой список, а не 403: эти три ручки кормят КАРТОЧКУ задачи
    (`useLabels`/`useStages`/`useCustomFieldDefinitions`), и 403 там дал бы
    гостю тост об ошибке вместо тихой деградации. Там, где ответ — агрегат по
    всем задачам проекта (значения полей, состав участников), остаётся 403
    через `assert_full_project_access`.
    """
    return personal_task_scope(project, principal) is not None


def personal_display_name(
    project: Project, principal: Principal, *, owner_name: str | None = None
) -> str:
    """Имя проекта ГЛАЗАМИ вызывающего.

    Своё личное с 16.09 называется «Мои задачи» — и ровно поэтому гостю его так
    показывать нельзя: автор поручения, открыв карточку, прочитал бы «Проект:
    Мои задачи» про чужой инбокс. Подменяем на «Личное · Имя», когда имя
    владельца известно вызывающему, и на «Личное» — когда нет.

    Приватность не страдает: гость и так участник этого личного пространства и
    видит фамилию владельца в номере задачи (`PETRPOPOV-5`). Наружу по-прежнему
    не уходит `personal_owner_id` — только строка.
    """
    if personal_task_scope(project, principal) is None:
        return project.name
    return f"Личное · {owner_name}" if owner_name else "Личное"


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
