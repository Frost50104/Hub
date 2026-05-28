"""Auto-generate a unique project `key` from the human-facing `name`.

Strategy:
1. Transliterate Cyrillic to Latin (one-letter mapping; lossy but stable).
2. Split by whitespace; if 2+ words — initials (first letter of each, max 4).
3. Single word — first 6 alphanumerics (must start with a letter).
4. Fallback — `PROJ`.
5. Append a numeric suffix `2`, `3`, … if the candidate is already used in
   the tenant (cap at 999 to avoid pathological inputs).

Returned key always matches `^[A-Z][A-Z0-9_-]*$` and `len ≤ 32`.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project

_CYRILLIC_MAP = str.maketrans(
    {
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
        "Е": "E", "Ё": "E", "Ж": "Z", "З": "Z", "И": "I",
        "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N",
        "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
        "У": "U", "Ф": "F", "Х": "H", "Ц": "C", "Ч": "C",
        "Ш": "S", "Щ": "S", "Ъ": "",  "Ы": "Y", "Ь": "",
        "Э": "E", "Ю": "Y", "Я": "Y",
    }
)

_FALLBACK = "PROJ"
_MAX_LEN = 16  # leave room for numeric suffix without exceeding 32 char limit


def _candidate(name: str) -> str:
    """Compute the base candidate key from a name (without collision check)."""
    transliterated = name.translate(_CYRILLIC_MAP).upper()
    words = re.findall(r"[A-Z0-9]+", transliterated)
    if not words:
        return _FALLBACK
    if len(words) >= 2:
        initials = "".join(w[0] for w in words if w[0].isalpha())[:4]
        if initials and initials[0].isalpha():
            return initials
    cleaned = re.sub(r"^[^A-Z]+", "", words[0])
    if not cleaned:
        return _FALLBACK
    return cleaned[:_MAX_LEN]


async def generate_unique_key(
    db: AsyncSession, *, name: str, tenant_id: UUID
) -> str:
    base = _candidate(name)
    rows = await db.execute(
        select(Project.key).where(
            Project.tenant_id == tenant_id, Project.key.like(f"{base}%")
        )
    )
    used = {row[0] for row in rows.all()}
    if base not in used:
        return base
    for i in range(2, 1000):
        candidate = f"{base}{i}"
        if candidate not in used:
            return candidate
    # Pathological: 999 collisions on the same base. Astronomically unlikely
    # but we still don't want a 500 — surface as 409 in caller.
    raise ValueError(f"could not allocate unique key starting with {base!r}")
