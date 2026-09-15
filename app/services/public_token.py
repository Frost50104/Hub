"""Helpers for the public-share-token feature (3.6.12).

Two responsibilities:
- `load_active_token(session, token)` — look up a token cross-tenant, filter
  revoked/expired. Caller decides what to do with it.
- `_initials(name, email)` — produce a 1-2 letter pseudonym for sanitized
  payloads ("Иван И." → "ИИ"). Never returns email parts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share import PublicShareToken
from app.services.mention_parser import normalize_token

# Синхронизировано с грамматикой токена (`app/services/mention_parser.py`
# и `web/src/lib/mentions.ts`). Граница перед `@` здесь СОЗНАТЕЛЬНО не
# проверяется: на публичной странице маскируются и почты, набранные в тексте
# руками.
_MENTION_RE = re.compile(r"@([\w.\-]+)")


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


def mask_mentions(body: str, names_by_token: dict[str, str]) -> str:
    """Sanitize @mentions in comment bodies for anonymous public payloads.

    Токен упоминания — либо логин почты («@petr.popov.1104»), либо ФИО через
    подчёркивание («@Иван_Петров»). Логин в странице без логина — частичные
    ПДн, поэтому известные токены раскрываются в отображаемое имя, а всё
    неизвестное (включая почты, набранные в тексте руками) схлопывается до
    первой буквы. Сознательно агрессивно: приватность важнее точности показа.
    """

    def _sub(m: re.Match[str]) -> str:
        raw = m.group(1)
        core = raw.rstrip(".-")
        tail = raw[len(core) :]
        if not core:
            return m.group(0)
        name = names_by_token.get(normalize_token(raw))
        if name:
            return f"@{name}{tail}"
        return f"@{core[0]}…{tail}"

    return _MENTION_RE.sub(_sub, body)
