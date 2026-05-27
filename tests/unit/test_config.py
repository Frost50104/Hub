"""Smoke test for Settings — defaults load, env override works."""

from __future__ import annotations

import pytest

from app.config import get_settings


def test_defaults_load() -> None:
    s = get_settings()
    assert s.environment == "test"
    assert s.signaris_auth_issuer == "auth.signaris.ru"
    assert s.vapid_subject == "mailto:ops@signaris.ru"
    assert s.attachment_max_bytes == 20 * 1024 * 1024


def test_cors_origins_default_contains_both_envs() -> None:
    s = get_settings()
    assert "https://hub-staging.signaris.ru" in s.cors_origins
    assert "https://hub.signaris.ru" in s.cors_origins


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNARIS_HUB_PORT", "9999")
    get_settings.cache_clear()
    assert get_settings().port == 9999
