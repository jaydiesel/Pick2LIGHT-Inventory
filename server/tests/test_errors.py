import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel


class Body(BaseModel):
    name: str


@pytest.fixture
async def error_client(app):
    from pick2light.errors import Conflict, ValidationFailed

    router = APIRouter()

    @router.get("/api/v1/_t/conflict")
    async def conflict():
        raise Conflict("in use")

    @router.get("/api/v1/_t/invalid")
    async def invalid():
        raise ValidationFailed({"name": "required"})

    @router.post("/api/v1/_t/body")
    async def body(b: Body):
        return b

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_conflict_shape(error_client):
    r = await error_client.get("/api/v1/_t/conflict")
    assert r.status_code == 409
    assert r.json() == {"error": "conflict", "message": "in use"}


async def test_validation_failed_shape(error_client):
    r = await error_client.get("/api/v1/_t/invalid")
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    assert r.json()["fields"] == {"name": "required"}


async def test_request_validation_shape(error_client):
    r = await error_client.post("/api/v1/_t/body", json={})
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    assert "name" in r.json()["fields"]
