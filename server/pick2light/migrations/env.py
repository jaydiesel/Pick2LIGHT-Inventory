import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import pick2light.models  # noqa: F401 - registers all models on Base.metadata
from pick2light.config import get_settings
from pick2light.models.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Programmatic callers (CLI, tests) pass the URL via cfg.attributes; otherwise settings.
    return str(config.attributes.get("url") or get_settings().database_url)


def _configure(connection: Connection | None = None) -> None:
    context.configure(
        connection=connection,
        url=None if connection else _url(),
        target_metadata=target_metadata,
        literal_binds=connection is None,
        compare_type=True,
    )


def run_migrations_offline() -> None:
    _configure()
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
