"""@mention parser for comments.

Токен упоминания — `@` и дальше буквы (любого алфавита), цифры, `_`, `.`, `-`.
Две формы, обе легальны и обе резолвятся:

- **имя** — `@Иван_Петров`: ФИО, где пробелы заменены на `_`. Основная форма
  с 14.09: сотрудник жаловался, что «невозможно написать через @ имя и
  фамилию, приходится смотреть логин в почте» — а логины на проде в 140
  случаях из 227 содержат цифры и в 122 случаях это личный gmail/yandex.
- **логин** — `@petr.popov`: local-part почты. Остаётся навсегда: так написаны
  все существующие комментарии и так шлют застрявшие PWA-бандлы.

Какую форму вставить, решает СЕРВЕР в `/api/tenant/members` (поле `mention`,
см. `app/services/people_search.py`): токен-имя выдаётся только уникальному и
«безопасному» ФИО, иначе логин.

**Неоднозначный токен-имя не резолвится ни в кого.** На проде 2 пары полных
тёзок; попасть в текст такой токен может только ручным набором, а уведомить —
и теперь ещё и впустить в проект — не того человека хуже, чем промолчать.

Упоминания, которые ни во что не резолвятся, игнорируются молча: текст в теле
остаётся, но ни автоподписки, ни уведомления не будет.

Регулярка живёт в ТРЁХ местах и меняется только тройкой:
`app/services/mention_parser.py`, `app/services/public_token.py`,
`web/src/lib/mentions.ts`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shadow import ShadowUser
from app.services.people_search import normalize, normalized_col

# `(?:^|[^\w])@` — boundary so `email@host` is not parsed as mention `@host`.
# `\w` в питоновских str-паттернах юникодный, поэтому кириллица сюда входит.
_MENTION_RE = re.compile(r"(?:^|[^\w])@([\w.\-]+)")


def normalize_token(raw: str) -> str:
    """Токен к каноничному виду: нижний регистр, `ё`→`е`, без хвостовых `.`/`-`.

    Хвост срезаем, потому что `.` и `-` нужны внутри логинов (`@petr.popov`),
    но в конце они почти всегда пунктуация: «позовите @Иван_Петров.» иначе не
    резолвился бы.
    """
    return normalize(raw).rstrip(".-")


def extract_mentions(text: str) -> list[str]:
    """Уникальные нормализованные токены из текста, в порядке появления."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _MENTION_RE.findall(text):
        token = normalize_token(raw)
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _token_columns() -> tuple[object, object]:
    """SQL-выражения обеих форм токена для сравнения с нормализованным вводом."""
    name_token = func.replace(
        func.btrim(normalized_col(ShadowUser.full_name)), " ", "_"
    )
    handle = normalized_col(func.split_part(ShadowUser.email, "@", 1))
    return name_token, handle


async def _lookup(
    session: AsyncSession, *, tokens: list[str], tenant_id: UUID
) -> dict[str, tuple[UUID, str | None]]:
    """token → (employee_id, ФИО) для ОДНОЗНАЧНЫХ токенов."""
    if not tokens:
        return {}
    name_token, handle = _token_columns()
    rows = await session.execute(
        select(
            ShadowUser.employee_id,
            ShadowUser.full_name,
            name_token.label("name_token"),
            handle.label("handle"),
        ).where(
            ShadowUser.tenant_id == tenant_id,
            ShadowUser.deleted_at.is_(None),
            or_(name_token.in_(tokens), handle.in_(tokens)),
        )
    )
    wanted = set(tokens)
    hits: dict[str, dict[UUID, str | None]] = defaultdict(dict)
    for row in rows.all():
        for candidate in (row.name_token, row.handle):
            if candidate in wanted:
                hits[candidate][row.employee_id] = row.full_name
    return {
        token: next(iter(people.items()))
        for token, people in hits.items()
        if len(people) == 1
    }


async def resolve_mentions(
    session: AsyncSession, *, text: str, tenant_id: UUID
) -> list[UUID]:
    """Parse mentions from text and return matching employee_ids in this tenant."""
    tokens = extract_mentions(text)
    found = await _lookup(session, tokens=tokens, tenant_id=tenant_id)
    seen: set[UUID] = set()
    out: list[UUID] = []
    # Порядок — как в тексте: он же определяет порядок уведомлений.
    for token in tokens:
        hit = found.get(token)
        if hit is None or hit[0] in seen:
            continue
        seen.add(hit[0])
        out.append(hit[0])
    return out


async def mention_names(
    session: AsyncSession, *, texts: list[str], tenant_id: UUID
) -> dict[str, str]:
    """token → текущее ФИО: словарь для показа чипов «@Иван Петров».

    Один запрос на ВЕСЬ список комментариев. Раньше клиент строил такой
    словарь из `/tenant/members` с лимитом 10, и имя подставлялось только
    первым десяти сотрудникам по алфавиту — остальным навсегда оставался
    логин.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for token in extract_mentions(text):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    found = await _lookup(session, tokens=tokens, tenant_id=tenant_id)
    return {token: name for token, (_, name) in found.items() if name}


def render_mentions(text: str, names: dict[str, str]) -> str:
    """Подставить ФИО вместо токенов — для текстов уведомлений и пушей."""

    def _sub(m: re.Match[str]) -> str:
        raw = m.group(1)
        # Хвостовая пунктуация в токен не входит, но и пропасть не должна:
        # «позовите @Иван_Петров.» обязано остаться предложением с точкой.
        core = raw.rstrip(".-")
        tail = raw[len(core) :]
        name = names.get(normalize_token(raw))
        shown = name or core.replace("_", " ")
        return m.group(0).replace(f"@{raw}", f"@{shown}{tail}")

    return _MENTION_RE.sub(_sub, text)
