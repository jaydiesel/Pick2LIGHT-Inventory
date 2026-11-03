from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from fastapi import APIRouter
from pydantic import BaseModel

from pick2light.app import create_app
from pick2light.config import Settings
from pick2light.errors import Conflict, InvalidOperation, NotFound, ValidationFailed


class Body(BaseModel):
    name: str


router = APIRouter(prefix="/_t")


@router.get("/conflict")
async def _conflict() -> None:
    raise Conflict("in use")


@router.get("/invalid")
async def _invalid() -> None:
    raise ValidationFailed({"name": "required"})


@router.get("/missing")
async def _missing() -> None:
    raise NotFound("no such thing")


@router.get("/bad")
async def _bad() -> None:
    raise InvalidOperation("cannot do that")


@router.post("/body")
async def _body(body: Body) -> Body:
    return body


@pytest_asyncio.fixture
async def error_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(data_dir=tmp_path, secret_key="x"))
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_conflict_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.get("/api/v1/_t/conflict")
    assert r.status_code == 409
    assert r.json() == {"error": "conflict", "message": "in use"}


async def test_not_found_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.get("/api/v1/_t/missing")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "message": "no such thing"}


async def test_invalid_operation_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.get("/api/v1/_t/bad")
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_operation", "message": "cannot do that"}


async def test_validation_failed_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.get("/api/v1/_t/invalid")
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    assert r.json()["fields"] == {"name": "required"}


async def test_request_validation_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.post("/api/v1/_t/body", json={})
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    assert "name" in r.json()["fields"]


async def test_unknown_route_uses_error_shape(error_client: httpx.AsyncClient) -> None:
    r = await error_client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
