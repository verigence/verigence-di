"""Alembic environment configuration for Verigence DI.

Uses async SQLAlchemy engine (asyncpg) for all migrations.
The DI_DATABASE_URL env var is read at migration time so that
the same alembic.ini works across local, dev and production.
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic Config object — gives access to alembic.ini values
config = context.config

# Override sqlalchemy.url from environment variable
database_url = os.environ.get("DI_DATABASE_URL")
if database_url:
    # asyncpg driver required; normalise prefix
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("postgresql://", "postgresql+asyncpg://")
        .replace("postgres://", "postgresql+asyncpg://"),
    )

# Logging setup from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# We use plain SQL migrations (not ORM metadata autogenerate)
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (useful for SQL script generation)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Use docintel schema for alembic_version table
        version_table_schema="docintel",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
