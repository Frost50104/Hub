"""Integration-фикстуры: Postgres 16 в testcontainers + alembic upgrade head.

Один контейнер на сессию тестов; каждый тест получает СВЕЖУЮ БД-схему не
получает — данные изолируются уникальными tenant_id (RLS) per-test.
Redis не поднимаем: тестируемые здесь сервисы (audience/profiles) его не
трогают.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pg_container():
    # pgvector-образ: alembic head (0028) требует EXTENSION vector.
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_url(pg_container: PostgresContainer) -> str:
    raw = pg_container.get_connection_url()  # postgresql+psycopg2://...
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session", autouse=True)
def _migrated(database_url: str):
    """Прогнать все миграции один раз на контейнер."""
    os.environ["SIGNARIS_HUB_DATABASE_URL"] = database_url
    os.environ["SIGNARIS_HUB_DATABASE_MIGRATION_URL"] = database_url

    from app.config import get_settings

    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def _fresh_engine(database_url: str):
    """Пересоздать engine на каждый тест (event loop pytest-asyncio per-test)."""
    from app.db import reset_engine

    await reset_engine()
    yield
    await reset_engine()


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db(tenant_id: uuid.UUID, _fresh_engine) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped сессия свежего тенанта (изоляция данных через RLS)."""
    from app.db import tenant_scoped_session

    async with tenant_scoped_session(tenant_id) as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def rls_enforced(database_url: str, _fresh_engine, monkeypatch):
    """Opt-in: переключить app-engine на NON-superuser роль → RLS реально enforced.

    Дефолтная роль testcontainers (`test`) — superuser и владелец таблиц:
    superuser обходит RLS безусловно (FORCE не помогает), поэтому обычные
    тесты политики не проверяют. Эта фикстура создаёт `hub_app_test`
    (NOSUPERUSER NOBYPASSRLS, по образцу deploy/bootstrap-vps.sh) и
    пересоздаёт engine на её DSN. Sequence-grants обязательны — Identity-PK.
    """
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import get_settings
    from app.db import reset_engine

    admin = create_async_engine(database_url, poolclass=NullPool)
    async with admin.begin() as conn:
        await conn.execute(
            sa_text(
                "DO $$ BEGIN IF NOT EXISTS "
                "(SELECT FROM pg_roles WHERE rolname = 'hub_app_test') THEN "
                "CREATE ROLE hub_app_test LOGIN PASSWORD 'app_pwd' "
                "NOSUPERUSER NOBYPASSRLS; END IF; END $$"
            )
        )
        await conn.execute(sa_text("GRANT USAGE ON SCHEMA public TO hub_app_test"))
        await conn.execute(
            sa_text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                "IN SCHEMA public TO hub_app_test"
            )
        )
        await conn.execute(
            sa_text(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hub_app_test"
            )
        )
    await admin.dispose()

    app_url = database_url.replace("//test:test@", "//hub_app_test:app_pwd@")
    assert app_url != database_url, "не удалось подменить креды в DSN"
    monkeypatch.setenv("SIGNARIS_HUB_DATABASE_URL", app_url)
    get_settings.cache_clear()
    await reset_engine()

    yield

    # Явный возврат ДО undo monkeypatch'а: engine не должен пережить тест
    # на app-роли (teardown _fresh_engine бежит позже и тоже сбросит).
    monkeypatch.setenv("SIGNARIS_HUB_DATABASE_URL", database_url)
    get_settings.cache_clear()
    await reset_engine()


def make_principal(
    tenant_id: uuid.UUID,
    *,
    email: str = "user@test.ru",
    full_name: str = "Тест Юзер",
    role: str = "member",
    tenant_slug: str = "test",
) -> Principal:
    """tenant_slug: тесты, которые КОММИТЯТ (endpoint-функции), обязаны
    передавать уникальный slug — иначе UNIQUE shadow_tenants.slug конфликтует
    между тестами (rollback-only тестам дефолт безопасен)."""
    return Principal(
        employee_id=uuid.uuid4(),
        email=email,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        full_name=full_name,
        product_roles={"hub": role},
        jti=str(uuid.uuid4()),
    )
