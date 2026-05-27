"""Pytest fixtures — env defaults for unit tests (no DB / no auth).

Integration tests (MVP.2+) will spin up Postgres via testcontainers and
override DATABASE_URL through `monkeypatch`. The unit-level fixtures here
just set safe defaults so importing `app.config` succeeds without a .env.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SIGNARIS_HUB_ENVIRONMENT", "test")
os.environ.setdefault(
    "SIGNARIS_HUB_DATABASE_URL",
    "postgresql+asyncpg://hub@localhost:5432/hub_test",
)
os.environ.setdefault("SIGNARIS_HUB_REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear cached Settings between tests so env-overrides take effect."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
