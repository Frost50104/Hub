"""Поиск человека по имени и почте — один алгоритм на все справочники.

Запрос сотрудника 14.09: «невозможно написать через @ имя и фамилию, Хаб не
находит человека в справочнике». Причина была не в попапе (там своя, см.
`web/src/lib/mentions.ts`), а в самом фильтре: обе ручки искали ОДНОЙ
подстрокой — `lower(full_name) LIKE '%иван петров%'`. Замер на проде: из 225
двухсловных ФИО при вводе слов в обратном порядке находилось **0**, а порядок
в справочнике смешанный — у 139 человек фамилия вторым словом, у 70 первым.

Поэтому здесь запрос режется на слова, и КАЖДОЕ слово обязано найтись в ФИО
или в почте (AND между словами, OR между колонками). «петров иван» и «иван
петров» находят одного и того же человека.

`ё` нормализуется в `е` с обеих сторон: на проде 5 человек с «ё» в имени, и
без этого «Семён» не искался по «семен». База в `C.UTF-8` — `lower()` кириллицу
обрабатывает (проверено на проде), локального .lower() в Python достаточно.

Индексов под `replace(lower(...))` не заводим сознательно: 227 живых теней и
305 учебных карточек, seq scan дешевле поддержки функционального индекса.

Потребители: `app/api/tenant.py` (упоминания, исполнители, наблюдатели,
фильтры) и `app/api/employees.py` (экран «Сотрудники»). Клиентское зеркало
правил токена упоминания — `web/src/lib/mentions.ts`.
"""

from __future__ import annotations

import re

from sqlalchemy import ColumnElement, String, and_, case, func, literal, or_

# Больше четырёх слов в имени не бывает, а каждое слово — ещё один LIKE.
MAX_TOKENS = 4
# Символы, из которых может состоять токен-имя в упоминании. Всё остальное
# (на проде это «/» у одного человека) делает имя непригодным для токена.
# `[^\W_]` — буква или цифра любого алфавита, но не «_»: точное зеркало
# постгресового `[[:alnum:]]` (под C.UTF-8 он кириллицу принимает, проверено).
# «_» запрещён и как разделитель: он означает пробел в токене, и живое ФИО
# «Иван_Петров» дало бы тот же токен, что «Иван Петров» — чужое упоминание.
_TOKEN_SAFE = re.compile(r"^[^\W_]+(?:[ .-][^\W_]+)*$")
_SPACES = re.compile(r"\s+")


def normalize(value: str) -> str:
    """Схлопнуть пробелы, привести к нижнему регистру, `ё` → `е`."""
    return _SPACES.sub(" ", value).strip().lower().replace("ё", "е")


def query_tokens(q: str | None) -> list[str]:
    """Запрос → слова для поиска. Пустой запрос даёт пустой список."""
    if not q:
        return []
    return [t for t in normalize(q).split(" ") if t][:MAX_TOKENS]


def normalized_col(col: ColumnElement[str | None]) -> ColumnElement[str]:
    """SQL-двойник `normalize` для колонки (без схлопывания пробелов)."""
    return func.replace(func.lower(func.coalesce(col, "")), "ё", "е")


def match_condition(
    name_col: ColumnElement[str | None],
    email_col: ColumnElement[str | None],
    q: str | None,
) -> ColumnElement[bool] | None:
    """Условие «каждое слово запроса есть в ФИО или в почте». None — не фильтруем."""
    words = query_tokens(q)
    if not words:
        return None
    name = normalized_col(name_col)
    email = normalized_col(email_col)
    return and_(
        *(
            or_(name.like(f"%{w}%"), email.like(f"%{w}%"))
            for w in words
        )
    )


def rank_expr(
    name_col: ColumnElement[str | None],
    email_col: ColumnElement[str | None],
    q: str | None,
) -> ColumnElement[int]:
    """0 — ФИО (или слово в нём) начинается с запроса, 1 — почта с него, 2 — прочее.

    Раньше сортировка была чистым алфавитом, и при частом префиксе в первую
    десятку попадали не самые релевантные люди, а самые ранние по алфавиту.
    """
    words = query_tokens(q)
    if not words:
        return literal(0)
    first = words[0]
    name = normalized_col(name_col)
    email = normalized_col(email_col)
    return case(
        (or_(name.like(f"{first}%"), name.like(f"% {first}%")), 0),
        (email.like(f"{first}%"), 1),
        else_=2,
    )


def mention_token_expr(
    name_col: ColumnElement[str | None],
    email_col: ColumnElement[str | None],
    twins_col: ColumnElement[int],
) -> ColumnElement[str]:
    """Готовый токен упоминания: `Имя_Фамилия` либо логин почты.

    Токен-имя выдаётся, только если ФИО непустое, состоит из безопасных
    символов и в тенанте уникально (`twins_col` = сколько людей с таким же
    нормализованным ФИО). На проде это отсекает 2 пары полных тёзок и одного
    человека со «/» в имени — им достаётся логин, который резолвится всегда.

    Проверку «безопасных символов» в SQL делаем regexp'ом, зеркалящим
    `is_token_safe`: две реализации одного правила, но SQL-версия нужна, чтобы
    не тащить весь справочник в Python ради одного поля.
    """
    trimmed = func.btrim(func.coalesce(name_col, ""), type_=String)
    handle = func.lower(func.split_part(func.coalesce(email_col, ""), "@", 1))
    return case(
        (
            and_(
                trimmed != "",
                twins_col == 1,
                trimmed.op("~")(r"^[[:alnum:]]+([ .-][[:alnum:]]+)*$"),
            ),
            func.replace(trimmed, " ", "_"),
        ),
        else_=handle,
    )


def is_token_safe(full_name: str) -> bool:
    """Годится ли ФИО в токен-имя (питоновское зеркало `mention_token_expr`)."""
    trimmed = _SPACES.sub(" ", full_name).strip()
    return bool(trimmed) and bool(_TOKEN_SAFE.match(trimmed))


def name_to_token(full_name: str) -> str:
    """`Иван Петров` → `Иван_Петров`. Вызывать только при `is_token_safe`."""
    return _SPACES.sub(" ", full_name).strip().replace(" ", "_")


def token_to_name(token: str) -> str:
    """`Иван_Петров` → `Иван Петров` — для показа, когда человека уже нет."""
    return token.replace("_", " ")
