import asyncio
import logging
import os
from logging.config import fileConfig

from sqlalchemy import pool as sqlalchemy_pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from alembic import context
from nba_wins_pool.models import *  # noqa: F403

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use (if present)
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# When using pyproject.toml, config_file_name may be None or point to non-existent file
if config.config_file_name is not None and os.path.exists(config.config_file_name):
    fileConfig(config.config_file_name)
else:
    # Set up basic logging when no config file is available
    logging.basicConfig(level=logging.INFO)

# add your model's MetaData object here
# for 'autogenerate' support

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@database:5432/nba_wins_pool")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Use environment variable directly
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@database:5432/nba_wins_pool")

    connectable = create_async_engine(
        db_url,
        poolclass=sqlalchemy_pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
