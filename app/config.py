"""Pydantic settings for Signaris Hub backend.

All env vars are prefixed SIGNARIS_HUB_* — e.g. SIGNARIS_HUB_DATABASE_URL.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIGNARIS_HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Environment
    environment: str = Field(default="staging")
    app_version: str = Field(default="0.0.0-dev")
    port: int = Field(default=5060)
    debug_rls: bool = Field(default=False)

    # Database (app role for runtime; migrate role for alembic upgrades)
    database_url: str = Field(default="postgresql+asyncpg://signaris_hub@localhost:5432/signaris_hub_db")
    database_migration_url: str | None = Field(default=None)

    # Redis (DB 4 prod / 5 staging — see CLAUDE.md)
    redis_url: str = Field(default="redis://127.0.0.1:6379/5")

    # signaris-auth integration
    signaris_auth_jwks_url: str = Field(default="https://auth.signaris.ru/.well-known/jwks.json")
    signaris_auth_issuer: str = Field(default="auth.signaris.ru")
    signaris_auth_base_url: str = Field(default="https://auth.signaris.ru")
    signaris_service_key: str | None = Field(default=None)
    deletion_sync_enabled: bool = Field(default=True)
    deletion_sync_poll_sec: float = Field(default=60.0)

    # Sid-sync (Phase 2 SLO) — фоновый воркер опрашивает фид ревокации SSO-сессий
    # (GET /api/products/revoked-sids, X-Service-Key) и держит локальный
    # blacklist `sso_session_id`'ов. `require_auth` отказывает в access-токенах
    # с ревокнутым sid мгновенно (≤ poll-интервал), не дожидаясь access-TTL.
    # См. `app/services/sid_sync.py`.
    sid_sync_enabled: bool = Field(default=True)
    sid_sync_poll_sec: float = Field(default=30.0)

    # CORS — staging + prod fronts
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "https://hub-staging.signaris.ru",
            "https://hub.signaris.ru",
        ]
    )

    # VAPID (Web Push, Hub-MVP.4)
    vapid_public_key: str | None = Field(default=None)
    vapid_private_key_path: Path | None = Field(default=None)
    vapid_subject: str = Field(default="mailto:ops@signaris.ru")

    # Sentry (Hub-MVP.5)
    sentry_dsn: str | None = Field(default=None)

    # Attachments (Hub-MVP.5)
    attachments_root: Path = Field(default=Path("/opt/signaris-hub/attachments"))
    attachment_max_bytes: int = Field(default=20 * 1024 * 1024)

    # Public links (3.6.12) — view-only no-auth deep-links to a task/project.
    # Feature-flag so we can kill-switch the entire surface without a redeploy.
    public_links_enabled: bool = Field(default=True)
    # Used to build the absolute URL returned by `POST /api/.../share`.
    public_base_url: str = Field(default="https://hub.signaris.ru")


@lru_cache
def get_settings() -> Settings:
    return Settings()
