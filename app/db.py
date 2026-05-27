"""SQLAlchemy async engine + tenant-scoped session with Postgres RLS.

`tenant_scoped_session` ставит `app.tenant_id` (или `app.bypass_rls=on` для
системных воркеров) в Postgres GUC — RLS-policies на доменных таблицах
читают эти переменные через `current_setting()`.

Скопировано 1:1 с CentralAuthService/app/db.py:62-120 — единый паттерн для
всех продуктов экосистемы.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_log = structlog.get_logger("db")


class Base(DeclarativeBase):
    """Base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def reset_engine() -> None:
    """Dispose engine + session factory. Used by tests on DSN swap."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def tenant_scoped_session(
    tenant_id: UUID | None,
    *,
    bypass_rls: bool = False,
) -> AsyncIterator[AsyncSession]:
    """Open a session bound to a tenant via Postgres session vars.

    - tenant_id=None + bypass_rls=True: system worker, RLS off.
    - tenant_id=UUID  + bypass_rls=False: normal tenant scope, RLS enforced.
    - tenant_id=None  + bypass_rls=False: rejected.
    """
    if tenant_id is None and not bypass_rls:
        raise ValueError("tenant_id required unless bypass_rls=True")

    factory = get_session_factory()
    async with factory() as session:
        # Connection may be reused — always reset both vars first.
        await session.execute(text("SELECT set_config('app.bypass_rls', '', false)"))
        await session.execute(text("SELECT set_config('app.tenant_id', '', false)"))
        if bypass_rls:
            await session.execute(
                text("SELECT set_config('app.bypass_rls', 'on', false)")
            )
        else:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, false)"),
                {"tid": str(tenant_id)},
            )

        if get_settings().debug_rls:
            row = (
                await session.execute(
                    text(
                        "SELECT current_setting('app.tenant_id', true), "
                        "current_setting('app.bypass_rls', true), current_user"
                    )
                )
            ).one()
            _log.info(
                "rls.session",
                requested_tenant_id=str(tenant_id) if tenant_id else None,
                requested_bypass=bypass_rls,
                pg_tenant_id=row[0],
                pg_bypass_rls=row[1],
                pg_user=row[2],
            )

        yield session
