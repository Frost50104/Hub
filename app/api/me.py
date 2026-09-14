"""GET /api/me — authenticated identity + hub roles + learn-профиль.

Минимальный SSO-эндпоинт (Hub-MVP.1) + точка матчинга HR-карточки (Ф0 LMS):
для principals С hub-ролью идемпотентно привязываем/создаём employee_profile
по lower(email). Для юзеров других продуктов Signaris (hub_role=None) профиль
НЕ создаётся — иначе они засоряли бы оргструктуру.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.learn_home import AUTH_AVATAR_BASE
from app.deps import get_db, require_auth, require_auth_any
from app.services.employee_profiles import ensure_profile_for_principal
from app.services.guides import GuideLink, guides_for_role
from app.services.personal_projects import ensure_personal_project
from app.services.project_access import can_create_project
from app.services.user_prefs import get_theme, set_theme

router = APIRouter(tags=["me"])


class MeProfile(BaseModel):
    id: UUID
    org_role: str
    content_role: str
    status: str
    position_id: UUID | None
    store_id: UUID | None
    status_text: str | None


class MeResponse(BaseModel):
    employee_id: UUID
    email: str
    full_name: str
    tenant_id: UUID
    tenant_slug: str
    hub_role: str | None
    # Публичный аватар из auth; фронт делает <img> с фолбэком на инициалы
    # (у аккаунтов без фото auth отдаёт 404).
    avatar_url: str
    # Learn-профиль: None у юзеров без hub-роли; needs_restore=True — карточка
    # с этим email в архиве, требуется восстановление админом (повторный найм).
    profile: MeProfile | None = None
    profile_needs_restore: bool = False
    # Может ли создавать проекты и папки (admin или офис/ТУ/франчайзи) —
    # считает СЕРВЕР (project_access.can_create_project), фронт не выводит
    # правило из ролей сам.
    can_create_projects: bool = False
    # Персональный проект «Личное»: скрыт из всех списков проектов, секция на
    # /my работает обычными /projects/{id}/tasks. None — у principal нет
    # hub-роли либо проект не удалось создать (фронт деградирует в «секции
    # нет», а не в ошибку).
    personal_project_id: UUID | None = None
    # Инструкции по работе в Hub: готовые ПОДПИСАННЫЕ ссылки, а не признак
    # роли. Ссылка обязана быть в руках до клика — `window.open` после `await`
    # блокируют попап-фильтры; подпись стабильна в пределах часа, поэтому
    # повторные ответы /me не заставляют браузер перекачивать документ.
    guides: list[GuideLink] = []
    # Тема оформления — свойство УЧЁТНОЙ ЗАПИСИ, а не браузера (ОС 09.09: на
    # общем устройстве второй вошедший получал тему первого). None — выбор ещё
    # не сделан, и фронт вправе засеять его локальным (lib/themeSync.ts);
    # ОТСУТСТВИЕ поля целиком (старый бэкенд в окне деплоя) он трактует как
    # «синхронизации нет» и работает по-старому, per-device.
    theme: Literal["light", "dark"] | None = None


@router.get("/me", response_model=MeResponse)
async def get_me(
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    # /me — identity endpoint: anyone with a valid Signaris JWT can read it
    # (no `roles=[...]` filter). UI uses `hub_role=None` to render the
    # "no access to Hub" state instead of looping through SSO.
    hub_role = principal.role_for("hub")
    profile_payload: MeProfile | None = None
    needs_restore = False
    personal_project_id: UUID | None = None

    if hub_role is not None:
        result = await ensure_profile_for_principal(db, principal)
        # Коммитим ДО личного проекта: ensure_personal_project при коллизии
        # ключа откатывает SAVEPOINT, и незафиксированная привязка профиля
        # попала бы в зону поражения.
        await db.commit()
        personal_project_id = await ensure_personal_project(db, principal)
        await db.commit()
        if result.outcome == "needs_restore":
            needs_restore = True
        elif result.profile is not None:
            profile_payload = MeProfile(
                id=result.profile.id,
                org_role=result.profile.org_role,
                content_role=result.profile.content_role,
                status=result.profile.status,
                position_id=result.profile.position_id,
                store_id=result.profile.store_id,
                status_text=result.profile.status_text,
            )

    can_create = (
        await can_create_project(db, principal) if hub_role is not None else False
    )
    # После коммитов выше: селект не должен попадать внутрь транзакции,
    # которую ensure_* могли откатить до SAVEPOINT.
    theme = await get_theme(db, principal.employee_id)
    return MeResponse(
        employee_id=principal.employee_id,
        email=principal.email,
        full_name=principal.full_name,
        tenant_id=principal.tenant_id,
        tenant_slug=principal.tenant_slug,
        hub_role=hub_role,
        avatar_url=f"{AUTH_AVATAR_BASE}/{principal.employee_id}",
        profile=profile_payload,
        profile_needs_restore=needs_restore,
        can_create_projects=can_create,
        personal_project_id=personal_project_id,
        guides=guides_for_role(hub_role),
        theme=theme,
    )


class PersonalProjectResponse(BaseModel):
    personal_project_id: UUID


@router.post("/me/personal-project", response_model=PersonalProjectResponse)
async def ensure_my_personal_project(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> PersonalProjectResponse:
    """Идемпотентно вернуть id личного проекта — ремонт, а не основной путь.

    Основной путь — `personal_project_id` в GET /me. Ручка нужна, когда там
    пришёл null (гонка, миграция не догнала, восстановленный после увольнения
    аккаунт): фронту есть что нажать вместо пустого экрана без объяснений.
    """
    project_id = await ensure_personal_project(db, principal)
    await db.commit()
    if project_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось создать личный проект — попробуйте позже",
        )
    return PersonalProjectResponse(personal_project_id=project_id)


class MePreferencesUpdate(BaseModel):
    """Тело всегда полное: набор настроек маленький, PATCH-семантика не нужна.

    `extra="forbid"` — как у остальных схем проекта: pydantic молча игнорирует
    лишний ключ, и клиент получал бы 200 на запрос, который сервер не выполнил.
    """

    model_config = ConfigDict(extra="forbid")

    theme: Literal["light", "dark"]


class MePreferencesResponse(BaseModel):
    theme: Literal["light", "dark"] | None


@router.put("/me/preferences", response_model=MePreferencesResponse)
async def put_my_preferences(
    body: MePreferencesUpdate,
    principal: Principal = Depends(require_auth_any()),
    db: AsyncSession = Depends(get_db),
) -> MePreferencesResponse:
    """Сохранить настройки интерфейса текущего пользователя.

    `require_auth_any()`, как и у GET /me: principal без hub-роли видит
    `NoAccessScreen`, но он внутри Shell — видит тему и вправе её менять.
    """
    await set_theme(
        db,
        employee_id=principal.employee_id,
        tenant_id=principal.tenant_id,
        theme=body.theme,
    )
    return MePreferencesResponse(theme=body.theme)
