"""DSL parser for advanced search (3.6.11).

Syntax (whitespace-separated tokens):
    free-form word(s)        → full-text part (joined with spaces)
    "quoted phrase"          → preserved verbatim in the text part
    field:value              → equality filter (exact match)
    field:<YYYY-MM-DD         → date comparison ("before")
    field:>YYYY-MM-DD         → date comparison ("after")
    field:=YYYY-MM-DD         → date equality
    assignee:me              → expands to caller's employee_id in the API layer

Supported fields:
    assignee  → assignee_id, accepts "me" or UUID string
    status    → status in {todo, in_progress, in_review, done}
    priority  → priority in {low, medium, high, urgent}
    due       → due_at, accepts date with <,>,= operator
    created   → created_at, accepts date with <,>,= operator

Multiple occurrences of the same field: last one wins.  Unknown fields are
ignored (kept in text part) — defensive vs typos like `asignee:me`.

Why regex over `lark`: five operators, no recursion, no precedence. A 30-line
regex pass is both simpler and easier to audit for injection (no value ever
reaches SQL unparameterised).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

VALID_STATUSES: set[str] = {"todo", "in_progress", "in_review", "done"}
VALID_PRIORITIES: set[str] = {"low", "medium", "high", "urgent"}
SUPPORTED_FIELDS: set[str] = {
    "assignee",
    "status",
    "priority",
    "due",
    "created",
}

_TOKEN_RE = re.compile(
    r"""
    \s*
    (?:
        "(?P<quoted>[^"]*)"            # "quoted phrase"
      | (?P<field>\w+):(?P<op>[<>=])?(?P<value>"[^"]*"|\S+)  # field:value
      | (?P<word>\S+)                  # bare word
    )
    """,
    re.VERBOSE,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass
class ParsedQuery:
    """Parsed result, ready to be compiled into SQL by the API layer."""

    text: str = ""
    assignee: str | None = None  # "me" or UUID-string
    status: str | None = None
    priority: str | None = None
    due_op: str | None = None  # "<", ">", "="
    due_date: date | None = None
    created_op: str | None = None
    created_date: date | None = None

    @property
    def has_filters(self) -> bool:
        return any(
            v is not None
            for v in (
                self.assignee,
                self.status,
                self.priority,
                self.due_date,
                self.created_date,
            )
        )


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _try_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _consume_field(
    field: str, op_: str | None, value: str, out: ParsedQuery
) -> bool:
    """Apply one field:value into `out`. Returns True if consumed (else falls
    through to text part — useful for unknown fields / malformed dates).
    """
    raw = _strip_quotes(value)

    if field == "assignee":
        if op_:
            return False  # assignee doesn't accept operators
        if raw == "me" or _UUID_RE.match(raw):
            out.assignee = raw
            return True
        return False

    if field == "status":
        if op_ or raw not in VALID_STATUSES:
            return False
        out.status = raw
        return True

    if field == "priority":
        if op_ or raw not in VALID_PRIORITIES:
            return False
        out.priority = raw
        return True

    if field == "due":
        parsed = _try_date(raw)
        if parsed is None:
            return False
        out.due_op = op_ or "="
        out.due_date = parsed
        return True

    if field == "created":
        parsed = _try_date(raw)
        if parsed is None:
            return False
        out.created_op = op_ or "="
        out.created_date = parsed
        return True

    return False  # Unknown field — leave whole `field:value` in text


def parse(query: str) -> ParsedQuery:
    """Tokenise + extract filters. Anything that doesn't match a known field
    or that fails value validation stays in `text` (so the user gets
    feedback "ничего не найдено" rather than a silent type-spelling bug).
    """
    out = ParsedQuery()
    text_parts: list[str] = []

    for match in _TOKEN_RE.finditer(query.strip()):
        if quoted := match.group("quoted"):
            text_parts.append(quoted)
            continue

        field = match.group("field")
        if field:
            op_ = match.group("op")
            value = match.group("value")
            if field.lower() in SUPPORTED_FIELDS and _consume_field(
                field.lower(), op_, value, out
            ):
                continue
            # Unrecognised field or malformed value: surface as raw text so
            # the user sees the typo in chips/empty-results.
            text_parts.append(f"{field}:{op_ or ''}{value}")
            continue

        if word := match.group("word"):
            text_parts.append(word)

    out.text = " ".join(text_parts).strip()
    return out
