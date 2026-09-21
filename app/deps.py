"""Global FastAPI dependencies — auth verifier + tenant-scoped DB + rate-limit.

Route signature:

    @router.get("/...")
    async def handler(
        principal: Principal = Depends(require_auth(roles=["admin", "member"])),
        db: AsyncSession = Depends(get_db),
    ): ...

`get_db` opens a `tenant_scoped_session` for the principal's tenant (RLS
enforced) and runs the shadow upsert in the same transaction —
INTEGRATION.md шаг 5.

Verifier is built at module import time: `JWKSCache` is lazy itself
(no HTTP at construction), and `build_require_auth(verifier)` is a pure
function. This lets us use `Depends(require_auth(...))` as a default
parameter without lifespan ordering surprises.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from signaris_auth import JWKSCache, Principal, RevokedSidStore, TokenVerifier
from signaris_auth.fastapi import build_require_auth
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.redis_client import get_redis
from app.security.rate_limit import RateLimitExceeded, check_and_increment

_settings = get_settings()
_jwks = JWKSCache(_settings.signaris_auth_jwks_url)
_verifier = TokenVerifier(jwks=_jwks, issuer=_settings.signaris_auth_issuer)
# Phase 2 SLO: locally-cached set of revoked sso_session_id'ов, обновляется
# фоновым воркером (см. `app/services/sid_sync.py`). `build_require_auth`
# после verify проверяет `principal.sso_session_id in store` → 401 мгновенно.
_revoked_sid_store = RevokedSidStore()
_require_auth_factory = build_require_auth(
    _verifier, revoked_sid_store=_revoked_sid_store
)


def get_revoked_sid_store() -> RevokedSidStore:
    """Expose store для воркера sid-sync."""
    return _revoked_sid_store


def require_auth(*, roles: list[str] | None = None) -> Callable:
    """Per-route dependency: validate Bearer JWT and check hub-product access.

    Even without explicit `roles=`, `build_require_auth(product="hub")` enforces
    a presence-check (any hub:* role) — that's the intended behavior for all
    business routes. Use `require_auth_any()` for endpoints that should accept
    any valid Signaris JWT regardless of product roles.
    """
    return _require_auth_factory(product="hub", roles=roles)


def require_auth_any() -> Callable:
    """Per-route dependency: any valid Signaris JWT, no product/role filter.

    Intended for identity endpoints (`/api/me`) where we want to render a
    "no Hub access" state to users without hub:* roles, instead of looping
    through SSO.
    """
    return _require_auth_factory()


async def get_principal(request: Request) -> Principal:
    """Read the Principal that `require_auth` placed on request.state."""
    return request.state.principal


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped session + shadow upsert on each authenticated request.

    Must be combined with `Depends(require_auth(...))` in the same route —
    otherwise `request.state.principal` is missing.
    """
    principal: Principal = request.state.principal
    async with tenant_scoped_session(principal.tenant_id) as session:
        await upsert_shadow_tenant(session, principal, table="shadow_tenants")
        await upsert_shadow_user(session, principal, table="shadow_users")
        await session.commit()
        yield session


# Path-параметры, по которым страница шаблона узнаёт свой объект. Имена
# сверены по роутерам: `successor_id` — у зависимостей задач; дочерние id
# (stage_id, attachment_id) открывают область явным вызовом в ручке.
_TEMPLATE_PROJECT_PARAMS = ("project_id",)
_TEMPLATE_TASK_PARAMS = ("task_id", "successor_id")


def _path_uuid(request: Request, names: tuple[str, ...]) -> UUID | None:
    for name in names:
        raw = request.path_params.get(name)
        if raw is None:
            continue
        # Вложенные зависимости FastAPI выполняет ДО проверки path-параметров
        # самой ручки: битый id (старый бандл на /projects/templates) без
        # этого ронял бы запрос в 500, а не в честный 422 от валидации.
        try:
            return UUID(str(raw))
        except ValueError:
            return None
    return None


async def get_db_template_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AsyncSession:
    """`get_db` для ручек «страницы проекта», которым разрешено видеть шаблон.

    Шаблоны (0060) прячет политика RLS; эта зависимость — единственный
    способ ручки страницы проекта увидеть шаблон. Лениво: сначала обычный
    `db.get` — нашёлся, значит объект живой (или уже видим), лежит в identity
    map, и ручка возьмёт его оттуда без лишнего запроса. Зонд — только при
    промахе. Режим по методу: GET/HEAD — смотреть (право видеть шаблоны),
    остальное — править (автор и hub-admin, иначе 403).

    Список ручек на этой зависимости сторожит юнит-тест реестра маршрутов:
    шаринг, перенос, папки, архив и статистика шаблон видеть не должны.
    """
    from app.services.project_access import open_template_if_hidden

    project_id = _path_uuid(request, _TEMPLATE_PROJECT_PARAMS)
    task_id = None if project_id else _path_uuid(request, _TEMPLATE_TASK_PARAMS)
    if project_id is None and task_id is None:
        return db
    await open_template_if_hidden(
        db,
        request.state.principal,
        project_id=project_id,
        task_id=task_id,
        mode=template_mode_for(request.method),
    )
    return db


def template_mode_for(method: str) -> str:
    """GET/HEAD — смотреть шаблон; всё остальное — править (автор и admin)."""
    return "view" if method in ("GET", "HEAD") else "edit"


async def enforce_rate_limit(
    *,
    bucket: str,
    employee_id: str,
    limit: int,
    window_sec: int,
) -> None:
    """Wrap `check_and_increment` and translate `RateLimitExceeded` → HTTP 429.

    `bucket` is a short label (`task:write`, `search`, `comment`, `attach`)
    that namespaces the Redis key alongside the employee id.
    """
    try:
        await check_and_increment(
            get_redis(),
            key=f"{bucket}:{employee_id}",
            limit=limit,
            window_sec=window_sec,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком часто. Лимит {e.limit} за {e.window_sec}с — подождите минуту.",
            headers={"Retry-After": str(e.window_sec)},
        ) from None
