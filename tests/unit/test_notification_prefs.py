"""Unit tests for `app.services.notification_prefs`.

Verifies the normaliser handles three legacy shapes:
- empty / None (new user, default both channels on)
- bool-shape (pre-3.6.7 deploys — both channels follow the bool)
- dict-shape (post-3.6.7 — push and in_app are independent)
"""

from __future__ import annotations

from app.services.notification_prefs import (
    NOTIFICATION_KINDS,
    normalize_prefs,
    should_send_inapp,
    should_send_push,
)


def test_normalize_none_yields_all_kinds_enabled() -> None:
    prefs = normalize_prefs(None)
    assert set(prefs.keys()) == set(NOTIFICATION_KINDS)
    for kind in NOTIFICATION_KINDS:
        assert prefs[kind] == {"push": True, "in_app": True}


def test_normalize_empty_dict_same_as_none() -> None:
    assert normalize_prefs({}) == normalize_prefs(None)


def test_normalize_legacy_bool_true_keeps_both_channels_on() -> None:
    prefs = normalize_prefs({"task.assigned_to_me": True})
    assert prefs["task.assigned_to_me"] == {"push": True, "in_app": True}


def test_normalize_legacy_bool_false_disables_both_channels() -> None:
    prefs = normalize_prefs({"task.mentioned": False})
    assert prefs["task.mentioned"] == {"push": False, "in_app": False}
    # Other kinds retain defaults.
    assert prefs["task.assigned_to_me"] == {"push": True, "in_app": True}


def test_normalize_dict_shape_passes_through() -> None:
    prefs = normalize_prefs({"task.due_soon": {"push": False, "in_app": True}})
    assert prefs["task.due_soon"] == {"push": False, "in_app": True}


def test_normalize_partial_dict_fills_missing_channel_with_default() -> None:
    prefs = normalize_prefs({"task.overdue": {"push": False}})
    assert prefs["task.overdue"] == {"push": False, "in_app": True}


def test_normalize_unknown_kind_is_dropped() -> None:
    prefs = normalize_prefs({"task.unknown_future_kind": True})
    assert "task.unknown_future_kind" not in prefs
    # Real kinds still present with defaults.
    for kind in NOTIFICATION_KINDS:
        assert kind in prefs


def test_normalize_garbage_value_falls_back_to_default() -> None:
    prefs = normalize_prefs({"task.mentioned": "yes-please"})
    assert prefs["task.mentioned"] == {"push": True, "in_app": True}


def test_should_send_helpers_default_to_true_for_missing_kind() -> None:
    prefs = normalize_prefs(None)
    assert should_send_inapp(prefs, "task.assigned_to_me") is True
    assert should_send_push(prefs, "task.assigned_to_me") is True


def test_should_send_helpers_honour_per_channel_off() -> None:
    prefs = normalize_prefs({"task.due_soon": {"push": False, "in_app": True}})
    assert should_send_push(prefs, "task.due_soon") is False
    assert should_send_inapp(prefs, "task.due_soon") is True
