"""Флаги, схемы и справочники «Гусиной гонки»: то, что молча ломает деплой."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.schemas.race import ContestCreate, ContestUpdate, RaceSettingsPut
from app.services.learn_settings import DEFAULTS
from app.services.notification_prefs import NOTIFICATION_KINDS, normalize_prefs
from app.services.timefmt import fmt_day, fmt_day_range


def test_flags_default_on_but_tenant_key_default_off(monkeypatch):
    monkeypatch.delenv("SIGNARIS_HUB_RACE_ENABLED", raising=False)
    monkeypatch.delenv("SIGNARIS_HUB_RACE_SYNC_ENABLED", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.race_enabled is True and s.race_sync_enabled is True
    assert DEFAULTS["race_enabled"] is False, "гонка появляется только там, где её включили"


def test_env_flag_can_switch_module_off(monkeypatch):
    monkeypatch.setenv("SIGNARIS_HUB_RACE_ENABLED", "false")
    get_settings.cache_clear()
    assert get_settings().race_enabled is False


def test_contest_create_rejects_wrong_length_and_extra_fields():
    ContestCreate(title="Осень", starts_on=date(2026, 9, 21))
    with pytest.raises(ValidationError):
        ContestCreate(title="Осень", starts_on=date(2026, 9, 21), race_length_days=10)
    with pytest.raises(ValidationError):
        ContestCreate(title="Осень", starts_on=date(2026, 9, 21), foo=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ContestUpdate(status="active")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RaceSettingsPut(enabled=True, extra=1)  # type: ignore[call-arg]


def test_race_kinds_are_known_to_preferences():
    assert "race.started" in NOTIFICATION_KINDS and "race.record" in NOTIFICATION_KINDS
    prefs = normalize_prefs({"race.record": {"push": False, "in_app": True}})
    assert prefs["race.record"] == {"push": False, "in_app": True}
    assert prefs["race.started"] == {"push": True, "in_app": True}


def test_fmt_day_range_russian():
    assert fmt_day(date(2026, 9, 21)) == "21 сентября"
    assert fmt_day_range(date(2026, 9, 21), date(2026, 9, 27)) == "21–27 сентября"
    assert fmt_day_range(date(2026, 9, 28), date(2026, 10, 4)) == "28 сентября — 4 октября"
    assert fmt_day_range(date(2026, 9, 1), date(2026, 9, 1)) == "1 сентября"
