import json

from sqlalchemy import select

from pick2light.core.settings import get_setting, set_settings
from pick2light.models import Category, LocationType

LOCATION_TYPES = {"Room", "Cabinet", "Drawer", "Shelf", "Bin", "Tote", "Box"}


async def test_setup_password_mode(fresh_client, db):
    res = await fresh_client.post(
        "/api/v1/setup",
        json={"auth_mode": "password", "password": "correct horse", "packs": ["generic"]},
    )
    assert res.status_code == 200, res.text
    assert "p2l_session" in res.cookies
    assert await get_setting(db, "setup.completed") is True
    assert await get_setting(db, "auth.mode") == "password"
    names = set(await db.scalars(select(LocationType.name)))
    assert names == LOCATION_TYPES
    assert await db.scalar(select(Category.id).where(Category.name == "General")) is not None
    # The cookie from setup is a working login.
    assert (await fresh_client.get("/api/v1/location-types")).status_code == 200


async def test_setup_none_mode(fresh_client, db):
    res = await fresh_client.post("/api/v1/setup", json={"auth_mode": "none", "packs": []})
    assert res.status_code == 200, res.text
    assert "p2l_session" not in res.cookies
    assert await get_setting(db, "auth.mode") == "none"
    assert await get_setting(db, "setup.completed") is True
    assert len(list(await db.scalars(select(LocationType)))) == 7


async def test_setup_twice_conflict(fresh_client):
    body = {"auth_mode": "none", "packs": []}
    assert (await fresh_client.post("/api/v1/setup", json=body)).status_code == 200
    again = await fresh_client.post("/api/v1/setup", json=body)
    assert again.status_code == 409
    assert again.json()["error"] == "conflict"


async def test_setup_password_required(fresh_client, db):
    res = await fresh_client.post("/api/v1/setup", json={"auth_mode": "password", "packs": []})
    assert res.status_code == 422
    assert "password" in res.json()["fields"]
    short = await fresh_client.post(
        "/api/v1/setup", json={"auth_mode": "password", "password": "abc", "packs": []}
    )
    assert short.status_code == 422
    assert await get_setting(db, "setup.completed") is False


async def test_setup_unknown_pack(fresh_client, db):
    res = await fresh_client.post("/api/v1/setup", json={"auth_mode": "none", "packs": ["nope"]})
    assert res.status_code == 404
    assert await get_setting(db, "setup.completed") is False
    assert list(await db.scalars(select(LocationType))) == []


async def test_setup_applies_packs(fresh_client, db):
    res = await fresh_client.post(
        "/api/v1/setup", json={"auth_mode": "none", "packs": ["batteries", "hardware"]}
    )
    assert res.status_code == 200
    names = set(await db.scalars(select(Category.name)))
    assert {"Batteries", "Li-ion Cells", "Hardware", "Screws/Bolts"} <= names


async def test_packs_api(client):
    listing = (await client.get("/api/v1/packs")).json()
    assert {p["id"] for p in listing} >= {"electronics", "hardware", "batteries"}

    res = await client.post("/api/v1/packs/apply", json={"pack_id": "batteries"})
    assert res.status_code == 200
    assert res.json() == {"created": 2, "skipped": 0}
    assert (await client.post("/api/v1/packs/apply", json={"pack_id": "nope"})).status_code == 404
    assert (await client.post("/api/v1/packs/apply", json={})).status_code == 422

    categories = (await client.get("/api/v1/categories")).json()
    batteries = next(c for c in categories if c["name"] == "Batteries")
    exported = await client.get(f"/api/v1/categories/{batteries['id']}/export-pack")
    assert exported.status_code == 200
    pack = exported.json()
    assert pack["location_types"] == []

    parent = (await client.post("/api/v1/categories", json={"name": "Spare"})).json()
    again = await client.post("/api/v1/packs/apply", json={"pack": pack, "parent_id": parent["id"]})
    assert again.json() == {"created": 2, "skipped": 0}

    upload = await client.post(
        "/api/v1/packs/import",
        files={"file": ("pack.json", json.dumps(pack), "application/json")},
    )
    assert upload.status_code == 200
    assert upload.json() == {"created": 0, "skipped": 2}
    bad = await client.post(
        "/api/v1/packs/import", files={"file": ("pack.json", "{not json", "application/json")}
    )
    assert bad.status_code == 422


async def test_packs_require_login(auth_client, db):
    await set_settings(db, {"setup.completed": True})
    assert (await auth_client.get("/api/v1/packs")).status_code == 401


async def test_packs_list_open_only_until_setup_completes(fresh_client):
    assert (await fresh_client.get("/api/v1/packs")).status_code == 200
    # Applying a pack stays protected even before setup.
    res = await fresh_client.post("/api/v1/packs/apply", json={"pack_id": "generic"})
    assert res.status_code == 401
    body = {"auth_mode": "password", "password": "correct horse"}
    done = await fresh_client.post("/api/v1/setup", json=body)
    assert done.status_code == 200
    fresh_client.cookies.clear()
    assert (await fresh_client.get("/api/v1/packs")).status_code == 401
