async def test_create_and_get_category(client):
    r = await client.post("/api/v1/categories", json={"name": "Electronics"})
    assert r.status_code == 201
    root = r.json()
    r = await client.post("/api/v1/categories", json={"name": "Resistors", "parent_id": root["id"]})
    child = r.json()
    r = await client.get(f"/api/v1/categories/{child['id']}")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()["path"]] == ["Electronics", "Resistors"]
    assert r.json()["path"][0]["id"] == root["id"]
    assert r.json()["effective_tracking_mode"] == "bulk"


async def test_fields_endpoint_marks_inherited(client):
    root = (await client.post("/api/v1/categories", json={"name": "Electronics"})).json()
    child = (await client.post("/api/v1/categories", json={"name": "Res", "parent_id": root["id"]})).json()
    r = await client.post(f"/api/v1/categories/{root['id']}/fields", json={"key": "datasheet", "type": "url"})
    assert r.status_code == 201
    await client.post(
        f"/api/v1/categories/{child['id']}/fields",
        json={"key": "resistance", "type": "number", "number_unit": "Ω", "number_si_prefixes": True},
    )
    fields = (await client.get(f"/api/v1/categories/{child['id']}/fields")).json()
    by_key = {f["key"]: f for f in fields}
    assert by_key["datasheet"]["inherited_from"] == root["id"]
    assert by_key["resistance"]["inherited_from"] is None


async def test_conflict_returns_409_shape(client):
    root = (await client.post("/api/v1/categories", json={"name": "Electronics"})).json()
    await client.post("/api/v1/categories", json={"name": "Res", "parent_id": root["id"]})
    r = await client.delete(f"/api/v1/categories/{root['id']}")
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"
    assert r.json()["message"]


async def test_missing_category_404(client):
    r = await client.get("/api/v1/categories/999999")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


async def test_location_types_crud(client):
    r = await client.post("/api/v1/location-types", json={"name": "Drawer", "icon": "drawer"})
    assert r.status_code == 201
    lt = r.json()
    r = await client.patch(f"/api/v1/location-types/{lt['id']}", json={"name": "Small drawer"})
    assert r.json()["name"] == "Small drawer"
    assert [t["name"] for t in (await client.get("/api/v1/location-types")).json()] == ["Small drawer"]
    assert (await client.delete(f"/api/v1/location-types/{lt['id']}")).status_code == 204
    assert (await client.get("/api/v1/location-types")).json() == []
