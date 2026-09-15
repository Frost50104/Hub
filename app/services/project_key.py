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

# Диграфы вместо однобуквенных замен (16.09): пока ключи собирались из
# названий проектов, «Ж→Z» и «Щ→S» были незаметны, но с ключом из ФИО они
# превращают Жужгину в ZUZGINA, а Щербакову в SERBAKOVA. Существующие ключи
# иммутабельны, так что правка касается только новых.
_CYRILLIC_MAP = str.maketrans(
    {
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
        "Е": "E", "Ё": "E", "Ж": "ZH", "З": "Z", "И": "I",
        "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N",
        "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
        "У": "U", "Ф": "F", "Х": "H", "Ц": "C", "Ч": "CH",
        "Ш": "SH", "Щ": "SCH", "Ъ": "", "Ы": "Y", "Ь": "",
        "Э": "E", "Ю": "YU", "Я": "YA",
    }
)

_FALLBACK = "PROJ"
_MAX_LEN = 16  # leave room for numeric suffix without exceeding 32 char limit


def _candidate(name: str, *, max_len: int = _MAX_LEN) -> str:
    """Compute the base candidate key from a name (without collision check).

    `max_len` — потолок БАЗЫ, а не готового ключа: суффикс коллизии клеится
    после среза. Полный ключ обязан уложиться в 16 символов — столько разрешает
    `_TASK_KEY_RE` ассистента, а он матчит «KEY-42» целиком.
    """
    # ВЕРХНИЙ РЕГИСТР ПЕРВЫМ. В таблице только заглавные буквы, поэтому
    # обратный порядок транслитерировал лишь первую букву обычного
    # русского названия, а остальные (строчные) выбрасывал фильтр ниже:
    # «Подбор линейного персонала» давал ключ «P», и все проекты подряд
    # получали P, P2, P3… вместо PLP.
    transliterated = name.upper().translate(_CYRILLIC_MAP)
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
    return cleaned[:max_len]


async def generate_unique_key(
    db: AsyncSession, *, name: str, tenant_id: UUID, max_len: int = _MAX_LEN
) -> str:
    base = _candidate(name, max_len=max_len)
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
