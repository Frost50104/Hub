"""@mention parser for comments.

Format: `@<local-part>` where local-part matches `[a-zA-Z0-9._-]+` and is
the part of an employee's email **before the `@`**. So writing `@petr.popov`
inside a comment resolves to the employee whose email is `petr.popov@uppetit.ru`.

The parser:
1. Extracts unique lower-cased local-parts from the text.
2. Looks them up against `shadow_users` in the current tenant (RLS already
   restricts to tenant; we also filter `deleted_at IS NULL`).

Mentions that don't resolve to a real employee are silently ignored — the
text stays as-is in the comment body, but they aren't auto-watched or
notified.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shadow import ShadowUser

# `(?:^|[^\w])@` — boundary so `email@host` is not parsed as mention `@host`.
_MENTION_RE = re.compile(r"(?:^|[^\w])@([a-zA-Z0-9._-]+)")


def extract_mentions(text: str) -> list[str]:
    """Return unique lowercase local-parts found in `text`, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _MENTION_RE.findall(text):
        normalized = raw.lower()
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


async def resolve_mentions(
    session: AsyncSession, *, text: str, tenant_id: UUID
) -> list[UUID]:
    """Parse mentions from text and return matching employee_ids in this tenant."""
    parts = extract_mentions(text)
    if not parts:
        return []
    rows = await session.execute(
        select(ShadowUser.employee_id).where(
            ShadowUser.tenant_id == tenant_id,
            ShadowUser.deleted_at.is_(None),
            func.lower(func.split_part(ShadowUser.email, "@", 1)).in_(parts),
        )
    )
    return [r[0] for r in rows.all()]
