from tests.factories import make_category, make_item, make_unit

RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}


async def test_item_crud(client, db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    r = await client.post(
        "/api/v1/items",
        json={"category_id": category.id, "name": "4k7", "attrs": {"resistance": "4.7k"}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["sku"] == "RESI-0001"
    assert body["attrs_display"]["resistance"] == "4.7kΩ"
    assert body["category_path"] == [{"id": category.id, "name": "Resistors"}]
    iid = body["id"]
    assert (await client.get(f"/api/v1/items/{iid}")).json()["name"] == "4k7"
    r = await client.patch(f"/api/v1/items/{iid}", json={"name": "4.7k", "min_stock": 5})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["min_stock"]) == ("4.7k", 5)
    assert (await client.delete(f"/api/v1/items/{iid}")).status_code == 204
    assert (await client.get(f"/api/v1/items/{iid}")).status_code == 404


async def test_attrs_validated(client, db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    r = await client.post(
        "/api/v1/items",
        json={"category_id": category.id, "name": "x", "attrs": {"resistance": "lots"}},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    assert "resistance" in r.json()["fields"]


async def test_item_loads_after_field_removed(client, db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    created = await client.post(
        "/api/v1/items",
        json={"category_id": category.id, "name": "x", "attrs": {"resistance": 4700}},
    )
    iid = created.json()["id"]
    fields = (await client.get(f"/api/v1/categories/{category.id}/fields")).json()
    assert (await client.delete(f"/api/v1/fields/{fields[0]['id']}")).status_code == 204
    r = await client.get(f"/api/v1/items/{iid}")
    assert r.status_code == 200
    assert r.json()["attrs"] == {"resistance": 4700}
    assert "resistance" not in r.json()["attrs_display"]


async def test_delete_item_with_stock_conflicts(client, db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    await make_unit(db, item)
    r = await client.delete(f"/api/v1/items/{item.id}")
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


async def test_unit_endpoints(client, db):
    cells = await make_category(db, "Cells", tracking_mode="unit", unit_id_pattern="C{seq:4}")
    item = await make_item(db, cells, "18650")
    r = await client.post("/api/v1/units", json={"item_id": item.id, "serial_number": "SN1"})
    assert r.status_code == 201
    unit = r.json()
    assert unit["unit_code"] == "C0001"
    assert unit["item"] == {"id": item.id, "name": "18650", "sku": item.sku}
    assert unit["location_path"] == []
    uid = unit["id"]
    r = await client.get(f"/api/v1/items/{item.id}/units")
    assert [u["id"] for u in r.json()] == [uid]
    r = await client.patch(f"/api/v1/units/{uid}", json={"condition": "tested_good"})
    assert r.json()["condition"] == "tested_good"
    assert (await client.get(f"/api/v1/units/{uid}")).status_code == 200
    assert (await client.delete(f"/api/v1/units/{uid}")).status_code == 204
    assert (await client.get(f"/api/v1/units/{uid}")).status_code == 404
    assert (await client.get(f"/api/v1/items/{item.id}/units")).json() == []


async def test_unit_in_bulk_category_is_400(client, db):
    bulk = await make_category(db, "Resistors")
    item = await make_item(db, bulk, "10k")
    r = await client.post("/api/v1/units", json={"item_id": item.id})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_operation"


async def test_manufacturer_barcodes_attach_to_items_and_units(client, db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    for target_type, target_id, code in (("item", item.id, "EAN-1"), ("unit", unit.id, "EAN-2")):
        r = await client.post(
            "/api/v1/barcodes",
            json={
                "code": code,
                "target_type": target_type,
                "target_id": target_id,
                "kind": "manufacturer",
            },
        )
        assert r.status_code == 201
    missing = await client.post(
        "/api/v1/barcodes",
        json={"code": "EAN-3", "target_type": "item", "target_id": 99999, "kind": "custom"},
    )
    assert missing.status_code == 404


async def test_stale_key_can_be_cleared_with_null(client, db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    iid = (
        await client.post(
            "/api/v1/items",
            json={"category_id": category.id, "name": "x", "attrs": {"resistance": 4700}},
        )
    ).json()["id"]
    fields = (await client.get(f"/api/v1/categories/{category.id}/fields")).json()
    await client.delete(f"/api/v1/fields/{fields[0]['id']}")
    r = await client.patch(f"/api/v1/items/{iid}", json={"attrs": {"resistance": 1}})
    assert r.status_code == 422  # unknown keys with a value are still rejected
    r = await client.patch(f"/api/v1/items/{iid}", json={"attrs": {"resistance": None}})
    assert r.status_code == 200
    assert r.json()["attrs"] == {}


async def test_stale_unit_key_can_be_cleared_with_null(client, db):
    cells = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "capacity", "type": "number", "scope": "unit"}],
    )
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, attrs={"capacity": 2500})
    fields = (await client.get(f"/api/v1/categories/{cells.id}/fields")).json()
    await client.delete(f"/api/v1/fields/{fields[0]['id']}")
    r = await client.patch(f"/api/v1/units/{unit.id}", json={"attrs": {"capacity": None}})
    assert r.status_code == 200
    assert r.json()["attrs"] == {}


async def test_field_type_change_after_items_exist(client, db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    item = await make_item(db, category, "x", attrs={"resistance": 4700})
    fields = (await client.get(f"/api/v1/categories/{category.id}/fields")).json()
    r = await client.patch(f"/api/v1/fields/{fields[0]['id']}", json={"type": "text"})
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/items/{item.id}")).status_code == 200
    r = await client.patch(f"/api/v1/items/{item.id}", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["attrs"] == {"resistance": 4700}


async def test_field_made_required_after_items_exist(client, db):
    category = await make_category(
        db, "Misc", fields=[{"key": "colour", "type": "text"}, {"key": "size", "type": "text"}]
    )
    item = await make_item(db, category, "x")
    fields = (await client.get(f"/api/v1/categories/{category.id}/fields")).json()
    colour = next(f for f in fields if f["key"] == "colour")
    r = await client.patch(f"/api/v1/fields/{colour['id']}", json={"required": True})
    assert r.status_code == 200
    r = await client.patch(f"/api/v1/items/{item.id}", json={"name": "renamed"})
    assert r.status_code == 200
    r = await client.patch(f"/api/v1/items/{item.id}", json={"attrs": {"size": "L"}})
    assert r.status_code == 422
    assert r.json()["fields"] == {"colour": "required"}
