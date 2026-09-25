"""Заморозка кадровых данных (16d): состояние для интерфейса и коды здоровья — без БД."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services import hr_state

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _row(**kw):
    base = {
        "authoritative": False,
        "cutover_freeze": False,
        "cutover_since": None,
        "pending_fingerprint": None,
        "pending_since": None,
        "last_applied_at": None,
        "authoritative_since": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _view(row, applying=True):
    return hr_state.derive_view(row, applying=applying, now=NOW, interval_sec=900)


def test_view_states():
    assert _view(None) == hr_state.NOT_FROZEN
    assert _view(_row()) == hr_state.NOT_FROZEN
    assert _view(_row(cutover_freeze=True)).state == "window"
    frozen = {"authoritative": True, "last_applied_at": NOW - timedelta(minutes=5)}
    assert _view(_row(**frozen, pending_fingerprint="x")).state == "blocked"
    assert _view(_row(**frozen), applying=False).state == "paused"
    assert _view(_row(**frozen)).state == "synced"
    old = {"authoritative": True, "last_applied_at": NOW - timedelta(minutes=50)}
    assert _view(_row(**old)).state == "stale"


def test_changed_hr_fields_only_real_changes():
    card = SimpleNamespace(
        hired_at=None, org_role="employee", position_id="p", store_id=None,
        department_id=None, franchisee_id=None, manager_profile_id=None,
    )
    assert hr_state.changed_hr_fields(card, {"position_id": "p", "phone": "+7"}) == []
    assert hr_state.changed_hr_fields(card, {"position_id": "q"}) == ["position_id"]


def test_health_problems():
    ok = _row(authoritative=True, authoritative_since=NOW - timedelta(days=1),
              last_applied_at=NOW - timedelta(minutes=10))
    assert hr_state.health_problems(ok, applying=True, now=NOW) == []
    # Заморожена, а применение не включено — сначала час форы (каткат идёт).
    fresh = _row(authoritative=True, authoritative_since=NOW - timedelta(minutes=20))
    assert hr_state.health_problems(fresh, applying=False, now=NOW) == []
    paused = _row(authoritative=True, authoritative_since=NOW - timedelta(hours=2))
    assert hr_state.health_problems(paused, applying=False, now=NOW) == ["paused"]
    stale = _row(authoritative=True, authoritative_since=NOW - timedelta(days=1),
                 last_applied_at=NOW - timedelta(hours=2))
    assert hr_state.health_problems(stale, applying=True, now=NOW) == ["stale"]
    blocked = _row(pending_fingerprint="x", pending_since=NOW - timedelta(hours=2))
    assert hr_state.health_problems(blocked, applying=True, now=NOW) == ["blocked"]
    window = _row(cutover_freeze=True, cutover_since=NOW - timedelta(hours=7))
    assert hr_state.health_problems(window, applying=True, now=NOW) == ["window_open"]
    # В окне «заморожено без применения» — норма: это и есть перенос.
    window_auth = _row(cutover_freeze=True, cutover_since=NOW - timedelta(hours=1),
                       authoritative=True, authoritative_since=NOW - timedelta(hours=3))
    assert hr_state.health_problems(window_auth, applying=False, now=NOW) == []


def test_tenant_applies_case_insensitive():
    assert hr_state.tenant_applies("UPPETIT", frozenset({"uppetit"}))
    assert not hr_state.tenant_applies(None, frozenset({"uppetit"}))
    assert not hr_state.tenant_applies("signaris", frozenset())
