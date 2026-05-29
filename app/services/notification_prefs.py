"""Notification preferences — normalisation, defaults, per-channel checks.

Two-tier shape, one row per user in `notification_preferences.prefs JSONB`:

    {
        "task.assigned_to_me":          {"push": true,  "in_app": true},
        "task.status_changed_on_watched": {"push": true,  "in_app": true},
        "task.mentioned":               {"push": true,  "in_app": true},
        "task.commented_on_watched":    {"push": true,  "in_app": true},
        "task.due_soon":                {"push": true,  "in_app": true},
        "task.overdue":                 {"push": true,  "in_app": true},
    }

Legacy migration: an older deploy stored `{kind: bool}` — both channels
enabled iff `True`. `normalize_prefs()` accepts that and rewrites in-memory.
No alembic migration: rewrite happens on the first PUT after upgrade.
"""

from __future__ import annotations

from typing import TypedDict

NOTIFICATION_KINDS: tuple[str, ...] = (
    "task.assigned_to_me",
    "task.status_changed_on_watched",
    "task.mentioned",
    "task.commented_on_watched",
    "task.due_soon",
    "task.overdue",
)


class KindPref(TypedDict):
    push: bool
    in_app: bool


_DEFAULT: KindPref = {"push": True, "in_app": True}


def normalize_prefs(raw: dict | None) -> dict[str, KindPref]:
    """Fill every known kind with a {push, in_app} dict.

    Accepts legacy bool-shape and dict-shape interchangeably so the UI
    always sees a consistent payload — and writers never need branching.
    Unknown kinds in `raw` are dropped (a no-op for future-prefixed keys
    we may add later).
    """
    out: dict[str, KindPref] = {}
    raw = raw or {}
    for kind in NOTIFICATION_KINDS:
        value = raw.get(kind)
        if value is None:
            out[kind] = dict(_DEFAULT)  # type: ignore[assignment]
        elif isinstance(value, bool):
            out[kind] = {"push": value, "in_app": value}
        elif isinstance(value, dict):
            out[kind] = {
                "push": bool(value.get("push", True)),
                "in_app": bool(value.get("in_app", True)),
            }
        else:
            out[kind] = dict(_DEFAULT)  # type: ignore[assignment]
    return out


def should_send_inapp(prefs: dict[str, KindPref], kind: str) -> bool:
    return prefs.get(kind, _DEFAULT).get("in_app", True)


def should_send_push(prefs: dict[str, KindPref], kind: str) -> bool:
    return prefs.get(kind, _DEFAULT).get("push", True)
