"""Global FastAPI dependencies — auth verifier + tenant-scoped DB.

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

from fastapi import Request
from signaris_auth import JWKSCache, Principal, RevokedSidStore, TokenVerifier
from signaris_auth.fastapi import build_require_auth
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session

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
