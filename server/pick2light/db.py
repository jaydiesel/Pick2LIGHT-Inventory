from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pick2light.config import get_settings


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_engine(get_settings().database_url), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Request-scoped session: commits when the request succeeds, rolls back on error."""
    async with _sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def dispose_engines() -> None:
    """Drop the pooled connections of the request engine (before a restore)."""
    if _sessionmaker.cache_info().currsize:
        await _sessionmaker().kw["bind"].dispose()


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    if url is not None:
        cfg.attributes["url"] = url
    return cfg


def upgrade_database(url: str | None = None) -> None:
    """Run `alembic upgrade head` (against `url`, or the configured database)."""
    command.upgrade(alembic_config(url), "head")
