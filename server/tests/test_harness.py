"""The shared-session test harness: `db` and `client` see the same transaction."""

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.api.deps import DB
from pick2light.errors import Conflict


async def test_failed_request_keeps_setup_data(
    app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    @app.get("/api/v1/_t/count")
    async def count(session: DB) -> dict[str, int]:
        return {"n": (await session.execute(text("SELECT count(*) FROM _t"))).scalar_one()}

    @app.get("/api/v1/_t/fail")
    async def fail() -> None:
        raise Conflict("nope")

    await db.execute(text("CREATE TEMP TABLE _t (x int)"))
    await db.execute(text("INSERT INTO _t VALUES (1)"))

    assert (await client.get("/api/v1/_t/fail")).status_code == 409
    r = await client.get("/api/v1/_t/count")
    assert r.json() == {"n": 1}
    assert (await db.execute(text("SELECT count(*) FROM _t"))).scalar_one() == 1
