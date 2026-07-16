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
    with PostgresContainer("postgres:16-alpine") as pg:
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


def make_principal(
    tenant_id: uuid.UUID,
    *,
    email: str = "user@test.ru",
    full_name: str = "Тест Юзер",
    role: str = "member",
) -> Principal:
    return Principal(
        employee_id=uuid.uuid4(),
        email=email,
        tenant_id=tenant_id,
        tenant_slug="test",
        full_name=full_name,
        product_roles={"hub": role},
        jti=str(uuid.uuid4()),
    )
