"""Helpers for the public-share-token feature (3.6.12).

Two responsibilities:
- `load_active_token(session, token)` — look up a token cross-tenant, filter
  revoked/expired. Caller decides what to do with it.
- `_initials(name, email)` — produce a 1-2 letter pseudonym for sanitized
  payloads ("Иван И." → "ИИ"). Never returns email parts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share import PublicShareToken


async def load_active_token(
    session: AsyncSession, token: UUID
) -> PublicShareToken | None:
    """Returns the token row iff it exists, isn't revoked, and isn't expired.

    Runs cross-tenant (no RLS on `public_share_tokens`). Caller MUST switch
    to that token's tenant_id (with `bypass_rls=True`) before querying any
    other table.
    """
    row = await session.execute(
        select(PublicShareToken).where(PublicShareToken.token == token)
    )
    record = row.scalar_one_or_none()
    if record is None:
        return None
    if record.revoked_at is not None:
        return None
    if record.expires_at is not None and record.expires_at < datetime.now(UTC):
        return None
    return record


def initials(name: str | None, email: str | None) -> str | None:
    """Two-letter initials from full_name; fall back to first letter of email.

    Returns None when there is literally nothing usable — so the UI renders
    «Аноним» instead of leaking partial PII.
    """
    if name:
        parts = [p for p in name.strip().split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        if parts:
            return parts[0][:2].upper()
    if email:
        # Just the first letter of the local-part — never @-suffix.
        local = email.split("@", 1)[0]
        if local:
            return local[0].upper()
    return None
