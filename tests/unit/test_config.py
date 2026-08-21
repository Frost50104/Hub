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


def test_app_version_reads_version_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """deploy.sh пишет VERSION (git-hash) в корень — /api/env.version берёт его,
    а не константу «0.1.0-bootstrap» (QA-0821 #1)."""
    from app import config as config_module

    (tmp_path / "VERSION").write_text("abc1234-dirty-20260821T1200\n")
    monkeypatch.setattr(config_module, "_PROJECT_ROOT", tmp_path)
    assert config_module._read_version_file() == "abc1234-dirty-20260821T1200"
    (tmp_path / "VERSION").write_text("   \n")
    assert config_module._read_version_file() == "0.0.0-dev"
    (tmp_path / "VERSION").unlink()
    assert config_module._read_version_file() == "0.0.0-dev"


def test_display_timezone_default_moscow() -> None:
    assert get_settings().display_timezone == "Europe/Moscow"
