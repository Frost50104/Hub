"""FastAPI app factory + lifespan: JWKS warmup, deletion-sync worker, Sentry."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import log as log_config
from app.config import get_settings

log = structlog.get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log_config.configure()
    settings = get_settings()

    if settings.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.asyncio import AsyncioIntegration
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                integrations=[
                    FastApiIntegration(),
                    SqlalchemyIntegration(),
                    AsyncioIntegration(),
                ],
                environment=settings.environment,
                release=settings.app_version,
                traces_sample_rate=0.05,
            )
            log.info("sentry.initialized", environment=settings.environment)
        except ImportError:
            log.warning(
                "sentry.sdk_missing",
                hint="pip install 'signaris-hub[sentry]' to enable",
            )

    # Auth verifier is created at module import time in app.deps —
    # no explicit init here. JWKSCache fetches keys lazily on first verify.
    log.info(
        "hub.starting",
        environment=settings.environment,
        port=settings.port,
        version=settings.app_version,
    )

    deletion_task: asyncio.Task | None = None
    if settings.signaris_service_key and settings.deletion_sync_enabled:
        from app.services.deletion_sync import start_worker

        deletion_task = asyncio.create_task(start_worker())
        log.info("deletion_sync.task_created")
    else:
        log.info(
            "deletion_sync.disabled",
            reason="SIGNARIS_HUB_SIGNARIS_SERVICE_KEY missing or disabled",
        )

    try:
        yield
    finally:
        if deletion_task is not None:
            deletion_task.cancel()
            try:
                await deletion_task
            except asyncio.CancelledError:
                pass
        log.info("hub.stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Signaris Hub",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "prod" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment != "prod" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Auth-Mode",
            "X-Request-Id",
        ],
    )

    from app.api import env as env_api
    from app.api import me as me_api

    app.include_router(env_api.router, prefix="/api")
    app.include_router(me_api.router, prefix="/api")

    return app


app = create_app()
