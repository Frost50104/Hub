"""GET /api/env — public bootstrap config for the SPA.

The frontend reads version (for UpdateBanner), vapid_public_key (for push
subscribe) and sentry_dsn (for Sentry init) from this endpoint. Anonymous
access — no auth.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["env"])


class EnvResponse(BaseModel):
    version: str
    environment: str
    vapid_public_key: str | None
    sentry_dsn: str | None


@router.get("/env", response_model=EnvResponse)
async def get_env() -> EnvResponse:
    settings = get_settings()
    return EnvResponse(
        version=settings.app_version,
        environment=settings.environment,
        vapid_public_key=settings.vapid_public_key,
        sentry_dsn=settings.sentry_dsn,
    )
