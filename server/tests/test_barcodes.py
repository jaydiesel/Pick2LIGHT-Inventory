import pytest
from factories import make_location

from pick2light.core.barcodes import code_exists, lookup_barcode, register_barcode, remove_barcodes_for
from pick2light.errors import Conflict


async def test_register_barcode_conflict_other_target(db):
    a = await make_location(db, "A")
    b = await make_location(db, "B")
    await register_barcode(db, "X123", "location", a.id, "custom")
    with pytest.raises(Conflict):
        await register_barcode(db, "X123", "location", b.id, "custom")


async def test_register_same_target_idempotent(db):
    a = await make_location(db, "A")
    first = await register_barcode(db, "X123", "location", a.id, "custom")
    again = await register_barcode(db, "X123", "location", a.id, "custom")
    assert first.id == again.id


async def test_lookup_case_insensitive_unique(db):
    a = await make_location(db, "A", code="LOC-0001X")
    assert (await lookup_barcode(db, "loc-0001x")).target_id == a.id
    b = await make_location(db, "B")
    await register_barcode(db, "Ab", "location", a.id, "custom")
    await register_barcode(db, "AB", "location", b.id, "custom")
    assert await lookup_barcode(db, "ab") is None
    assert (await lookup_barcode(db, "AB")).target_id == b.id


async def test_remove_and_exists(db):
    a = await make_location(db, "A")
    await register_barcode(db, "Z9", "location", a.id, "custom")
    assert await code_exists(db, "Z9")
    await remove_barcodes_for(db, "location", a.id, kind="custom")
    assert not await code_exists(db, "Z9")
    assert await code_exists(db, a.code)


async def test_api_locations_and_lookup(client):
    r = await client.post("/api/v1/locations", json={"name": "Garage"})
    assert r.status_code == 201
    garage = r.json()
    r = await client.post("/api/v1/locations", json={"name": "Cabinet", "parent_id": garage["id"]})
    cab = r.json()
    office = (await client.post("/api/v1/locations", json={"name": "Office"})).json()
    r = await client.get(f"/api/v1/locations/{cab['id']}")
    assert [p["name"] for p in r.json()["path"]] == ["Garage", "Cabinet"]
    r = await client.post(f"/api/v1/locations/{cab['id']}/move", json={"parent_id": office["id"]})
    assert r.status_code == 200 and r.json()["parent_id"] == office["id"]
    tree = (await client.get("/api/v1/locations/tree")).json()
    assert {n["name"] for n in tree} == {"Garage", "Office"}
    r = await client.get(f"/api/v1/barcodes/{cab['code']}")
    assert r.json()["target_type"] == "location" and r.json()["target_id"] == cab["id"]
    assert (await client.get("/api/v1/barcodes/NOPE")).status_code == 404
    r = await client.post(
        "/api/v1/barcodes", json={"code": "EAN123", "target_type": "location", "target_id": office["id"]}
    )
    assert r.status_code == 201 and r.json()["kind"] == "custom"
    assert (await client.delete(f"/api/v1/barcodes/{r.json()['id']}")).status_code == 204
    loc_code = (await client.get(f"/api/v1/barcodes/{office['code']}")).json()
    assert (await client.delete(f"/api/v1/barcodes/{loc_code['id']}")).status_code == 409
    assert (await client.delete(f"/api/v1/locations/{office['id']}")).status_code == 409
