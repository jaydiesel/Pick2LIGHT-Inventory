import pytest

from pick2light.core.auth import make_session_token, read_session_token, set_password
from pick2light.errors import ValidationFailed


async def test_login_sets_cookie_and_allows_access(auth_client, db):
    await set_password(db, "admin", "correct horse")
    assert (await auth_client.get("/api/v1/categories")).status_code == 401
    r = await auth_client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct horse"})
    assert r.status_code == 200 and "p2l_session" in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()
    assert (await auth_client.get("/api/v1/categories")).status_code == 200
    status = (await auth_client.get("/api/v1/auth/status")).json()
    assert status["authenticated"] is True and status["mode"] == "password"
    await auth_client.post("/api/v1/auth/logout")
    assert (await auth_client.get("/api/v1/categories")).status_code == 401


async def test_wrong_password_401(auth_client, db):
    await set_password(db, "admin", "correct horse")
    r = await auth_client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope nope"})
    assert r.status_code == 401 and r.json()["error"] == "unauthenticated"


async def test_protected_route_401_without_cookie(auth_client):
    r = await auth_client.get("/api/v1/categories")
    assert r.status_code == 401 and r.json()["error"] == "unauthenticated"


async def test_mode_none_allows_access(client):
    assert (await client.get("/api/v1/categories")).status_code == 200


async def test_public_routes_open(auth_client):
    for path in ("/api/v1/health", "/api/v1/auth/status", "/api/v1/settings/public"):
        assert (await auth_client.get(path)).status_code == 200, path


async def test_expired_token_rejected():
    token = make_session_token("s3cret", 1)
    assert read_session_token("s3cret", token) == 1
    assert read_session_token("other", token) is None
    assert read_session_token("s3cret", token, max_age_s=-1) is None


async def test_password_min_length(db):
    with pytest.raises(ValidationFailed):
        await set_password(db, "admin", "short")


async def test_change_password(auth_client, db):
    await set_password(db, "admin", "correct horse")
    await auth_client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct horse"})
    r = await auth_client.post(
        "/api/v1/auth/password", json={"current": "wrong one", "new": "battery staple"}
    )
    assert r.status_code == 401
    r = await auth_client.post(
        "/api/v1/auth/password", json={"current": "correct horse", "new": "battery staple"}
    )
    assert r.status_code == 204


async def test_settings_api(client):
    r = await client.patch("/api/v1/settings", json={"backup.keep": 5})
    assert r.status_code == 200 and r.json()["backup.keep"] == 5
    r = await client.patch("/api/v1/settings", json={"backup.keep": "x"})
    assert r.status_code == 422 and "backup.keep" in r.json()["fields"]
