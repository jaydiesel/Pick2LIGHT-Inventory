import pytest

from pick2light.core.barcodes import (
    code_exists,
    lookup_barcode,
    register_barcode,
    remove_barcodes_for,
)
from pick2light.errors import Conflict
from tests.factories import make_location


async def test_register_barcode_conflict_other_target(db):
    await register_barcode(db, "ABC123", "location", 1, "custom")
    with pytest.raises(Conflict):
        await register_barcode(db, "ABC123", "location", 2, "custom")
    with pytest.raises(Conflict):
        await register_barcode(db, "ABC123", "unit", 1, "custom")


async def test_register_same_target_idempotent(db):
    first = await register_barcode(db, "ABC123", "location", 1, "custom")
    again = await register_barcode(db, "ABC123", "location", 1, "custom")
    assert again.id == first.id


async def test_register_trims_code(db):
    barcode = await register_barcode(db, "  X-1 \n", "location", 1, "custom")
    assert barcode.code == "X-1"
    assert await code_exists(db, "X-1")
    assert not await code_exists(db, "x-1")


async def test_lookup_case_insensitive_unique(db):
    loc = await make_location(db, "Shelf")
    found = await lookup_barcode(db, loc.code.lower())
    assert found is not None and found.target_id == loc.id
    assert (await lookup_barcode(db, loc.code)) is not None
    assert await lookup_barcode(db, "nothing") is None

    await register_barcode(db, "Ab-1", "location", loc.id, "custom")
    await register_barcode(db, "aB-1", "location", loc.id, "custom")
    assert (await lookup_barcode(db, "Ab-1")).code == "Ab-1"  # exact match wins
    assert (await lookup_barcode(db, "aB-1")).code == "aB-1"
    assert await lookup_barcode(db, "AB-1") is None  # ambiguous, matches neither exactly


async def test_remove_barcodes_for_kind(db):
    await register_barcode(db, "A1", "location", 5, "custom")
    await register_barcode(db, "A2", "location", 5, "manufacturer")
    await remove_barcodes_for(db, "location", 5, kind="custom")
    assert await lookup_barcode(db, "A1") is None
    assert await lookup_barcode(db, "A2") is not None
    await remove_barcodes_for(db, "location", 5)
    assert await lookup_barcode(db, "A2") is None


async def test_api_lookup(client):
    loc = (await client.post("/api/v1/locations", json={"name": "Shelf"})).json()
    r = await client.get(f"/api/v1/barcodes/{loc['code'].lower()}")
    assert r.status_code == 200
    assert r.json() == {
        "id": r.json()["id"],
        "code": loc["code"],
        "target_type": "location",
        "target_id": loc["id"],
        "kind": "location_code",
    }
    assert (await client.get("/api/v1/barcodes/nope")).status_code == 404


async def test_api_create_and_delete_custom_barcode(client):
    loc = (await client.post("/api/v1/locations", json={"name": "Shelf"})).json()
    body = {"code": " 12345 ", "target_type": "location", "target_id": loc["id"], "kind": "custom"}
    r = await client.post("/api/v1/barcodes", json=body)
    assert r.status_code == 201
    assert r.json()["code"] == "12345"
    assert (await client.get("/api/v1/barcodes/12345")).json()["target_id"] == loc["id"]
    assert (await client.post("/api/v1/barcodes", json=body)).status_code == 201  # idempotent
    other = (await client.post("/api/v1/locations", json={"name": "Other"})).json()
    r = await client.post("/api/v1/barcodes", json={**body, "target_id": other["id"]})
    assert r.status_code == 409
    assert (await client.delete("/api/v1/barcodes/99999")).status_code == 404
    bid = (await client.get("/api/v1/barcodes/12345")).json()["id"]
    assert (await client.delete(f"/api/v1/barcodes/{bid}")).status_code == 204
    assert (await client.get("/api/v1/barcodes/12345")).status_code == 404


async def test_api_create_rejects_automatic_kinds_and_missing_targets(client):
    loc = (await client.post("/api/v1/locations", json={"name": "Shelf"})).json()
    for kind in ("sku", "unit_code", "location_code"):
        r = await client.post(
            "/api/v1/barcodes",
            json={"code": "ZZ", "target_type": "location", "target_id": loc["id"], "kind": kind},
        )
        assert r.status_code == 422
    r = await client.post(
        "/api/v1/barcodes",
        json={"code": "ZZ", "target_type": "location", "target_id": 99999, "kind": "custom"},
    )
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/barcodes",
        json={"code": "ZZ", "target_type": "item", "target_id": 99999, "kind": "custom"},
    )
    assert r.status_code == 404


async def test_api_delete_automatic_barcode_refused(client):
    loc = (await client.post("/api/v1/locations", json={"name": "Shelf"})).json()
    bid = (await client.get(f"/api/v1/barcodes/{loc['code']}")).json()["id"]
    r = await client.delete(f"/api/v1/barcodes/{bid}")
    assert r.status_code == 400
    assert (await client.get(f"/api/v1/barcodes/{loc['code']}")).status_code == 200
