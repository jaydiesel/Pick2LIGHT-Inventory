async def test_health_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["database"] == "ok"


async def test_openapi_served(client):
    r = await client.get("/api/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Pick2LIGHT-Inventory"
