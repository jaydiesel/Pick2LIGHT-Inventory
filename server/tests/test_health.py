import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light import __version__


async def test_health_ok(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok", "version": __version__}


async def test_health_degraded_when_database_fails(
    client: httpx.AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    async def boom(*args, **kwargs):
        raise OSError("db down")

    monkeypatch.setattr(db, "execute", boom)
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["database"] == "error"


async def test_openapi_served(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/openapi.json")
    assert r.status_code == 200 and r.json()["info"]["title"] == "Pick2LIGHT-Inventory"
