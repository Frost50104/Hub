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

    # Воркеры — под супервизором: рестарт с backoff при падении + Redis-лок
    # лидера, чтобы при uvicorn --workers N синхронизация бежала в одном
    # процессе (см. app/services/worker_supervisor.py).
    # ВАЖНО: --workers > 1 пока заблокирован sid-sync'ом — его revoked-store
    # живёт в памяти процесса; не-лидер не узнает о ревокациях. Для
    # масштабирования нужен Redis-backed store (см. docs/TECH_DEBT.md).
    from app.services.worker_supervisor import supervise

    deletion_task: asyncio.Task | None = None
    if settings.signaris_service_key and settings.deletion_sync_enabled:
        from app.services.deletion_sync import start_worker

        deletion_task = asyncio.create_task(supervise("deletion-sync", start_worker))
        log.info("deletion_sync.task_created")
    else:
        log.info(
            "deletion_sync.disabled",
            reason="SIGNARIS_HUB_SIGNARIS_SERVICE_KEY missing or disabled",
        )

    # Sid-sync worker (Phase 2 SLO) — опрашивает фид ревокаций SSO-сессий,
    # держит локальный blacklist, чтобы require_auth отказывал в access-токенах
    # с ревокнутым sid мгновенно (≤ poll-интервал), не дожидаясь access-TTL.
    sid_sync_task: asyncio.Task | None = None
    if settings.signaris_service_key and settings.sid_sync_enabled:
        from app.services.sid_sync import start_worker as start_sid_worker

        sid_sync_task = asyncio.create_task(supervise("sid-sync", start_sid_worker))
        log.info("sid_sync.task_created")
    else:
        log.info(
            "sid_sync.disabled",
            reason="SIGNARIS_HUB_SIGNARIS_SERVICE_KEY missing or sid_sync disabled",
        )

    try:
        yield
    finally:
        for task in (deletion_task, sid_sync_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        # Close the shared Redis connection pool — used by rate-limit + push fan-out.
        from app.redis_client import close_redis

        await close_redis()
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

    from app.api import activity as activity_api
    from app.api import attachments as attachments_api
    from app.api import audit as audit_api
    from app.api import automations as automations_api
    from app.api import calendar as calendar_api
    from app.api import comments as comments_api
    from app.api import courses as courses_api
    from app.api import custom_fields as custom_fields_api
    from app.api import dependencies as dependencies_api
    from app.api import employees as employees_api
    from app.api import env as env_api
    from app.api import favorites as favorites_api
    from app.api import labels as labels_api
    from app.api import learn_analytics as learn_analytics_api
    from app.api import learn_home as learn_home_api
    from app.api import learn_search as learn_search_api
    from app.api import library as library_api
    from app.api import me as me_api
    from app.api import me_tasks as me_tasks_api
    from app.api import media as media_api
    from app.api import news as news_api
    from app.api import notifications as notifications_api
    from app.api import org as org_api
    from app.api import products as products_api
    from app.api import projects as projects_api
    from app.api import public as public_api
    from app.api import push as push_api
    from app.api import quizzes as quizzes_api
    from app.api import search as search_api
    from app.api import sections as sections_api
    from app.api import share as share_api
    from app.api import stats as stats_api
    from app.api import surveys as surveys_api
    from app.api import tasks as tasks_api
    from app.api import tenant as tenant_api
    from app.api import timeline as timeline_api
    from app.api import watchers as watchers_api

    app.include_router(env_api.router, prefix="/api")
    app.include_router(me_api.router, prefix="/api")
    app.include_router(me_tasks_api.router, prefix="/api")
    app.include_router(projects_api.router, prefix="/api")
    app.include_router(sections_api.router, prefix="/api")
    app.include_router(tasks_api.router, prefix="/api")
    app.include_router(calendar_api.router, prefix="/api")
    app.include_router(custom_fields_api.router, prefix="/api")
    app.include_router(labels_api.router, prefix="/api")
    app.include_router(dependencies_api.router, prefix="/api")
    app.include_router(timeline_api.router, prefix="/api")
    app.include_router(share_api.router, prefix="/api")
    app.include_router(public_api.router, prefix="/api")
    app.include_router(comments_api.router, prefix="/api")
    app.include_router(watchers_api.router, prefix="/api")
    app.include_router(activity_api.router, prefix="/api")
    app.include_router(attachments_api.router, prefix="/api")
    app.include_router(search_api.router, prefix="/api")
    app.include_router(tenant_api.router, prefix="/api")
    app.include_router(push_api.router, prefix="/api")
    app.include_router(notifications_api.router, prefix="/api")
    app.include_router(stats_api.router, prefix="/api")
    # Learn-домен (LMS, Ф0+)
    app.include_router(org_api.router, prefix="/api")
    app.include_router(employees_api.router, prefix="/api")
    app.include_router(audit_api.router, prefix="/api")
    app.include_router(library_api.router, prefix="/api")
    app.include_router(news_api.router, prefix="/api")
    app.include_router(surveys_api.router, prefix="/api")
    app.include_router(favorites_api.router, prefix="/api")
    app.include_router(media_api.router, prefix="/api")
    app.include_router(courses_api.router, prefix="/api")
    app.include_router(quizzes_api.router, prefix="/api")
    app.include_router(products_api.router, prefix="/api")
    app.include_router(learn_home_api.router, prefix="/api")
    app.include_router(learn_search_api.router, prefix="/api")
    app.include_router(learn_analytics_api.router, prefix="/api")
    app.include_router(automations_api.router, prefix="/api")

    return app


app = create_app()
