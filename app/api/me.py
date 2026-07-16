"""GET /api/me — authenticated identity + hub roles + learn-профиль.

Минимальный SSO-эндпоинт (Hub-MVP.1) + точка матчинга HR-карточки (Ф0 LMS):
для principals С hub-ролью идемпотентно привязываем/создаём employee_profile
по lower(email). Для юзеров других продуктов Signaris (hub_role=None) профиль
НЕ создаётся — иначе они засоряли бы оргструктуру.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth_any
from app.services.employee_profiles import ensure_profile_for_principal

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
    # Learn-профиль: None у юзеров без hub-роли; needs_restore=True — карточка
    # с этим email в архиве, требуется восстановление админом (повторный найм).
    profile: MeProfile | None = None
    profile_needs_restore: bool = False


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

    if hub_role is not None:
        result = await ensure_profile_for_principal(db, principal)
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

    return MeResponse(
        employee_id=principal.employee_id,
        email=principal.email,
        full_name=principal.full_name,
        tenant_id=principal.tenant_id,
        tenant_slug=principal.tenant_slug,
        hub_role=hub_role,
        profile=profile_payload,
        profile_needs_restore=needs_restore,
    )
