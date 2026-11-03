import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Keep any accidental default-settings use out of the working tree.
os.environ.setdefault("P2L_DATA_DIR", tempfile.mkdtemp(prefix="p2l-test-data-"))

from pick2light.app import create_app  # noqa: E402
from pick2light.config import Settings  # noqa: E402
from pick2light.db import get_db, upgrade_database  # noqa: E402

ADMIN_URL = os.environ.get(
    "P2L_TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
)


@pytest_asyncio.fixture(scope="session")
async def database_url() -> AsyncIterator[str]:
    """Create a throwaway database, migrate it to head, drop it at session end."""
    name = f"p2l_test_{os.getpid()}"
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    try:
        # Alembic's async env runs its own event loop, so keep it off ours.
        await asyncio.to_thread(upgrade_database, url)
        yield url
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test session inside an outer transaction that is always rolled back.

    A session `commit()` only releases a savepoint. Code under test that needs to
    tolerate a failing statement should use `begin_nested()` rather than
    `rollback()`, which would also discard the test's earlier setup in this savepoint.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest_asyncio.fixture
async def committed_db(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions that really commit, for tests that need several independent transactions.

    Afterwards every app table is truncated and every sequence restarted, so later tests
    see the same empty database (and the same generated ids and codes) as before.
    `alembic_version` is left alone.
    """
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT quote_ident(tablename) FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
        ).scalars()
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        sequences = (
            await conn.execute(
                text(
                    "SELECT quote_ident(sequencename) FROM pg_sequences WHERE schemaname = 'public'"
                )
            )
        ).scalars()
        for name in list(sequences):
            await conn.execute(text(f"ALTER SEQUENCE {name} RESTART"))


@pytest.fixture
def settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(database_url=database_url, data_dir=tmp_path, secret_key="test-secret")


@pytest.fixture
def app(settings: Settings, db: AsyncSession) -> FastAPI:
    application = create_app(settings)

    # Requests share the test's session; unlike the real dependency this never
    # commits or rolls back, so a failing (4xx) request cannot undo test setup data.
    async def _shared_db() -> AsyncIterator[AsyncSession]:
        yield db

    application.dependency_overrides[get_db] = _shared_db
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
