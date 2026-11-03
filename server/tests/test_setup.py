async def test_setup_password_mode(auth_client):
    r = await auth_client.get("/api/v1/packs")
    assert r.status_code == 200 and len(r.json()) == 5
    r = await auth_client.post(
        "/api/v1/setup",
        json={
            "auth_mode": "password",
            "username": "admin",
            "password": "correct horse",
            "packs": ["batteries"],
        },
    )
    assert r.status_code == 200
    assert "p2l_session" in r.cookies
    status = (await auth_client.get("/api/v1/auth/status")).json()
    assert status["setup_completed"] is True and status["authenticated"] is True
    types = (await auth_client.get("/api/v1/location-types")).json()
    assert [t["name"] for t in types] == sorted(["Room", "Cabinet", "Drawer", "Shelf", "Bin", "Tote", "Box"])
    names = [c["name"] for c in (await auth_client.get("/api/v1/categories")).json()]
    assert "Li-ion Cells" in names


async def test_setup_none_mode(auth_client):
    r = await auth_client.post("/api/v1/setup", json={"auth_mode": "none", "packs": []})
    assert r.status_code == 200
    assert (await auth_client.get("/api/v1/categories")).status_code == 200


async def test_setup_password_too_short(auth_client):
    r = await auth_client.post(
        "/api/v1/setup", json={"auth_mode": "password", "password": "short", "packs": []}
    )
    assert r.status_code == 422 and "password" in r.json()["fields"]


async def test_setup_twice_conflict(auth_client):
    await auth_client.post("/api/v1/setup", json={"auth_mode": "none", "packs": []})
    r = await auth_client.post("/api/v1/setup", json={"auth_mode": "none", "packs": []})
    assert r.status_code == 409


async def test_pack_apply_and_export_api(client):
    r = await client.post("/api/v1/packs/apply", json={"pack_id": "generic"})
    assert r.status_code == 200 and r.json()["created"] == 1
    cat = next(c for c in (await client.get("/api/v1/categories")).json() if c["name"] == "General")
    r = await client.get(f"/api/v1/categories/{cat['id']}/export-pack")
    assert r.json()["categories"][0]["name"] == "General"
    r = await client.post("/api/v1/packs/import", files={"file": ("p.json", r.content, "application/json")})
    assert r.status_code == 200 and r.json()["skipped"] == 1
