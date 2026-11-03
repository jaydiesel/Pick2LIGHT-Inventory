import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

SERVER_DIR = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get(
    "P2L_TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
)
TEST_DB = f"p2l_test_{os.getpid()}"


def _plain(url: str) -> str:
    return url.replace("+asyncpg", "")


def _with_db(url: str, name: str) -> str:
    return url.rsplit("/", 1)[0] + "/" + name


def alembic_config(url: str) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "pick2light" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
async def database_url() -> AsyncIterator[str]:
    admin = await asyncpg.connect(_plain(ADMIN_URL))
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    await admin.close()
    url = _with_db(ADMIN_URL, TEST_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(url), "head")
    yield url
    admin = await asyncpg.connect(_plain(ADMIN_URL))
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await admin.close()


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest.fixture
def settings(database_url: str, tmp_path: Path):
    from pick2light.config import Settings

    return Settings(database_url=database_url, data_dir=tmp_path / "data", secret_key="test-secret")


@pytest.fixture
def app(settings, db: AsyncSession):
    from pick2light.app import create_app
    from pick2light.db import get_db

    application = create_app(settings)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        await db.commit()  # keep test setup; a failing request then rolls back only its own work
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture
async def auth_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """Client with the default auth mode (password) — requests need a login."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def client(app, db: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """Client with auth.mode = none so API tests don't need to log in."""
    from pick2light.core.settings import set_settings

    await set_settings(db, {"auth.mode": "none"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def committed_db(engine: AsyncEngine):
    """A sessionmaker whose sessions really commit; all app tables are truncated afterwards."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
            )
        )
        tables = ", ".join(f'"{r[0]}"' for r in rows)
        if tables:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
