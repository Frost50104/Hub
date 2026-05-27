"""Alembic env — sync engine (psycopg/asyncpg-sync via SQLAlchemy NullPool).

Migrations run from the BYPASSRLS migrate-role (DATABASE_MIGRATION_URL),
NOT the app role — see CLAUDE.md «Архитектура (hot)».
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401 — register all model mappings for autogenerate
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

settings = get_settings()
# Migrations use the migration role (BYPASSRLS). Fallback to runtime URL only
# in dev/local where one Postgres user owns everything.
config.set_main_option(
    "sqlalchemy.url",
    settings.database_migration_url or settings.database_url,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The app uses asyncpg at runtime; alembic is sync — swap to psycopg (v3).
    # Driver dependency is in pyproject.toml so `pip install -e .` provides both.
    url = config.get_main_option("sqlalchemy.url") or ""
    sync_url = url.replace("+asyncpg", "+psycopg")
    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
