async def test_item_and_unit_api(client):
    cat = (
        await client.post(
            "/api/v1/categories",
            json={"name": "Cells", "tracking_mode": "unit", "unit_id_pattern": "C{seq:4}"},
        )
    ).json()
    r = await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Samsung 30Q"})
    assert r.status_code == 201
    item = r.json()
    assert item["sku"] == "CELL-0001" and item["on_hand"] == 0
    r = await client.post("/api/v1/units", json={"item_id": item["id"]})
    assert r.status_code == 201 and r.json()["unit_code"] == "C0001"
    units = (await client.get(f"/api/v1/items/{item['id']}/units")).json()
    assert [u["unit_code"] for u in units] == ["C0001"]
    assert (await client.get(f"/api/v1/items/{item['id']}")).json()["on_hand"] == 1
    r = await client.patch(f"/api/v1/items/{item['id']}", json={"name": "30Q"})
    assert r.json()["name"] == "30Q"
    assert (await client.delete(f"/api/v1/items/{item['id']}")).status_code == 409
    assert (await client.delete(f"/api/v1/units/{units[0]['id']}")).status_code == 204


async def test_item_validation_422(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    r = await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "x", "attrs": {"nope": 1}})
    assert r.status_code == 422 and r.json()["fields"] == {"nope": "unknown field"}
