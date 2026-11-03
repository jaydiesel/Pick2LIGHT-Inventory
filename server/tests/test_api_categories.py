from tests.factories import make_category


async def test_create_and_get_category(client):
    r = await client.post("/api/v1/categories", json={"name": "Electronics"})
    assert r.status_code == 201
    root = r.json()
    r = await client.post("/api/v1/categories", json={"name": "Resistors", "parent_id": root["id"]})
    assert r.status_code == 201
    child = r.json()
    r = await client.get(f"/api/v1/categories/{child['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == [
        {"id": root["id"], "name": "Electronics"},
        {"id": child["id"], "name": "Resistors"},
    ]
    assert body["effective_tracking_mode"] == "bulk"
    listing = (await client.get("/api/v1/categories")).json()
    assert {c["id"] for c in listing} == {root["id"], child["id"]}
    assert next(c for c in listing if c["id"] == child["id"])["path"] == body["path"]


async def test_patch_and_delete_category(client):
    cid = (await client.post("/api/v1/categories", json={"name": "A"})).json()["id"]
    r = await client.patch(f"/api/v1/categories/{cid}", json={"tracking_mode": "unit"})
    assert r.json()["effective_tracking_mode"] == "unit"
    assert (await client.delete(f"/api/v1/categories/{cid}")).status_code == 204
    assert (await client.get(f"/api/v1/categories/{cid}")).status_code == 404


async def test_fields_endpoint_marks_inherited(db, client):
    root = await make_category(db, "Electronics", fields=[{"key": "datasheet", "type": "url"}])
    child = await make_category(
        db, "Resistors", parent=root, fields=[{"key": "resistance", "type": "number"}]
    )
    r = await client.get(f"/api/v1/categories/{child.id}/fields")
    assert r.status_code == 200
    by_key = {f["key"]: f for f in r.json()}
    assert by_key["datasheet"]["inherited_from"] == root.id
    assert by_key["resistance"]["inherited_from"] is None


async def test_field_crud(db, client):
    cat = await make_category(db)
    r = await client.post(
        f"/api/v1/categories/{cat.id}/fields",
        json={"key": "pkg", "label": "Package", "type": "text"},
    )
    assert r.status_code == 201
    fid = r.json()["id"]
    r = await client.patch(f"/api/v1/fields/{fid}", json={"label": "Pkg"})
    assert r.json()["label"] == "Pkg"
    assert (await client.delete(f"/api/v1/fields/{fid}")).status_code == 204
    assert (await client.get(f"/api/v1/categories/{cat.id}/fields")).json() == []


async def test_conflict_returns_409_shape(db, client):
    root = await make_category(db, "Electronics", fields=[{"key": "datasheet", "type": "url"}])
    child = await make_category(db, "Resistors", parent=root)
    r = await client.post(
        f"/api/v1/categories/{child.id}/fields",
        json={"key": "datasheet", "label": "D", "type": "url"},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


async def test_validation_shapes(db, client):
    cat = await make_category(db)
    r = await client.post(
        f"/api/v1/categories/{cat.id}/fields", json={"key": "pkg", "label": "P", "type": "select"}
    )
    assert r.status_code == 422 and "options" in r.json()["fields"]
    r = await client.post(
        f"/api/v1/categories/{cat.id}/fields", json={"key": "Bad", "label": "P", "type": "text"}
    )
    assert r.status_code == 422 and "key" in r.json()["fields"]


async def test_log_type_crud(db, client):
    cat = await make_category(db)
    r = await client.post(
        f"/api/v1/categories/{cat.id}/log-types",
        json={"key": "repair", "name": "Repair", "applies_to": "unit"},
    )
    assert r.status_code == 201
    lid = r.json()["id"]
    assert [
        t["key"] for t in (await client.get(f"/api/v1/categories/{cat.id}/log-types")).json()
    ] == ["repair"]
    r = await client.patch(f"/api/v1/log-types/{lid}", json={"name": "Repairs"})
    assert r.json()["name"] == "Repairs"
    assert (await client.delete(f"/api/v1/log-types/{lid}")).status_code == 204
    assert (await client.get(f"/api/v1/categories/{cat.id}/log-types")).json() == []


async def test_location_types_crud(client):
    r = await client.post("/api/v1/location-types", json={"name": "Drawer", "icon": "drawer"})
    assert r.status_code == 201
    lid = r.json()["id"]
    assert [t["name"] for t in (await client.get("/api/v1/location-types")).json()] == ["Drawer"]
    r = await client.patch(f"/api/v1/location-types/{lid}", json={"name": "Shelf"})
    assert r.json()["name"] == "Shelf"
    assert (await client.delete(f"/api/v1/location-types/{lid}")).status_code == 204
    assert (await client.get("/api/v1/location-types")).json() == []
    assert (
        await client.patch(f"/api/v1/location-types/{lid}", json={"name": "x"})
    ).status_code == 404
