"""SQLAlchemy async engine + tenant-scoped session with Postgres RLS.

`tenant_scoped_session` фиксирует желаемый RLS-скоуп (`app.tenant_id` или
`app.bypass_rls=on` для системных воркеров) в `session.info`; листенер
`_apply_rls_on_begin` проставляет GUC через `SET LOCAL` на старте КАЖДОЙ
транзакции — RLS-policies доменных таблиц читают их через `current_setting()`.

Паттерн after_begin — как в CentralAuthService/app/db.py (post-3cfb256,
фикс RLS-утечки через пул соединений 2026-05-31) — единый для всех
продуктов экосистемы.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings

_log = structlog.get_logger("db")

# Ключ в session.info, по которому листенер узнаёт желаемый RLS-скоуп
# (см. комментарий у листенера). Сырые `factory()`-сессии без этого ключа
# листенер игнорирует — для них GUC не ставятся вовсе (RLS fail-closed).
_RLS_INFO_KEY = "rls_scope"


class Base(DeclarativeBase):
    """Base for all ORM models."""


@event.listens_for(Session, "after_begin")
def _apply_rls_on_begin(session: Session, transaction, connection) -> None:  # noqa: ARG001
    """Set `app.tenant_id` / `app.bypass_rls` at the start of every transaction.

    ⚠ Почему именно так, а не «один раз при открытии сессии»:

    Engine использует пул (`pool_size=10` + overflow). SQLAlchemy-сессия НЕ
    закреплена за одним физическим соединением на всю жизнь — после каждого
    `commit()`/`rollback()` соединение возвращается в пул, а следующая
    транзакция той же сессии может взять ДРУГОЕ соединение. Если RLS-GUC
    выставлены session-level (`set_config(..., is_local=false)`) только при
    открытии сессии, то post-commit запросы (а `get_db` коммитит shadow-upsert
    ДО yield — то есть ВСЕ бизнес-запросы роутов) рискуют попасть на соединение
    со «stale» значением другого tenant'а или `bypass_rls='on'` от воркер-сессий
    (sid-sync/deletion-sync живут в том же пуле). Ровно это дало кросс-tenant
    утечку в проде 2026-08-01 (см. docs/TECH_DEBT.md).

    `after_begin` срабатывает в начале КАЖДОЙ транзакции и даёт нам нужное
    соединение → ставим оба GUC через `SET LOCAL` (is_local=true,
    транзакционно-скоупно). Это идемпотентно перезатирает любое унаследованное
    из пула значение и не протекает обратно в пул.

    Действуем только для сессий, помеченных `tenant_scoped_session` /
    `bypass_session_factory` (`session.info[_RLS_INFO_KEY]`); сырые
    `factory()`-сессии не трогаем.

    NB: `Session` здесь — sync-класс SQLAlchemy, AsyncSession проксирует его;
    листенер sync, `connection.execute(...)` синхронно отрабатывает в
    sync-секции async-стэка перед отправкой statement'а в asyncpg.
    """
    scope = session.info.get(_RLS_INFO_KEY)
    if scope is None:
        return
    tenant_id, bypass_rls = scope
    if bypass_rls:
        connection.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    else:
        connection.execute(text("SELECT set_config('app.bypass_rls', '', true)"))
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id) if tenant_id else ""},
        )


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


def bypass_session_factory() -> Callable[[], AsyncSession]:
    """Фабрика bypass-RLS сессий для внешних воркеров (deletion-sync из lib).

    Библиотечный `run_deletion_sync_worker` открывает сессии сам
    (`async with session_factory() as session`) и пишет в FORCE-RLS
    `shadow_users` — сырой фабрике без `session.info[_RLS_INFO_KEY]` листенер
    GUC не поставит, и `mark_shadow_deleted` молча обновлял бы 0 строк.
    Возвращаем callable, который помечает каждую сессию как bypass-RLS.
    """
    factory = get_session_factory()

    def _make() -> AsyncSession:
        return factory(info={_RLS_INFO_KEY: (None, True)})

    return _make


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
        # GUC (`app.tenant_id` / `app.bypass_rls`) проставляются листенером
        # `_apply_rls_on_begin` через `SET LOCAL` на старте КАЖДОЙ транзакции —
        # это переживает mid-request commit'ы и смену соединения в пуле (без
        # этого session-level set_config терялся после первого commit'а, и RLS
        # подставлял чужой tenant). Здесь только фиксируем желаемый скоуп.
        session.info[_RLS_INFO_KEY] = (tenant_id, bypass_rls)

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
