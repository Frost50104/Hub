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
from signaris_auth import JWKSCache, Principal, TokenVerifier
from signaris_auth.fastapi import build_require_auth
from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session

_settings = get_settings()
_jwks = JWKSCache(_settings.signaris_auth_jwks_url)
_verifier = TokenVerifier(jwks=_jwks, issuer=_settings.signaris_auth_issuer)
_require_auth_factory = build_require_auth(_verifier)


def require_auth(*, roles: list[str] | None = None) -> Callable:
    """Per-route dependency: validate Bearer JWT and optionally check `hub:*` roles."""
    return _require_auth_factory(product="hub", roles=roles)


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
