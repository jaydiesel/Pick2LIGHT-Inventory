import asyncio

import pytest

from pick2light.core.auth import (
    hash_password,
    make_session_token,
    read_session_token,
    set_password,
    verify_password,
)
from pick2light.core.settings import set_settings
from pick2light.errors import ValidationFailed

PASSWORD = "correct horse"


async def login(c, password=PASSWORD):
    return await c.post("/api/v1/auth/login", json={"username": "admin", "password": password})


def test_hash_and_verify():
    hashed = hash_password("secret-pass")
    assert hashed != "secret-pass"
    assert verify_password(hashed, "secret-pass")
    assert not verify_password(hashed, "other")
    assert not verify_password("garbage", "secret-pass")


def test_session_token_roundtrip():
    token = make_session_token("s", 7)
    assert read_session_token("s", token) == 7
    assert read_session_token("other", token) is None
    assert read_session_token("s", "junk") is None


async def test_expired_token_rejected():
    token = make_session_token("s", 7)
    await asyncio.sleep(1.1)
    assert read_session_token("s", token, max_age_s=0) is None


async def test_password_min_length(db):
    with pytest.raises(ValidationFailed) as exc:
        await set_password(db, "admin", "short")
    assert "password" in exc.value.fields


async def test_login_sets_cookie_and_allows_access(auth_client):
    r = await login(auth_client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "p2l_session=" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie
    assert (await auth_client.get("/api/v1/categories")).status_code == 200
    status = (await auth_client.get("/api/v1/auth/status")).json()
    assert status == {"mode": "password", "authenticated": True, "setup_completed": False}


async def test_wrong_password_401(auth_client):
    r = await login(auth_client, "nope-nope-nope")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"
    r = await auth_client.post("/api/v1/auth/login", json={"username": "x", "password": PASSWORD})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


async def test_protected_route_401_without_cookie(auth_client):
    for path in ("/api/v1/categories", "/api/v1/settings"):
        r = await auth_client.get(path)
        assert r.status_code == 401
        assert r.json()["error"] == "unauthenticated"
    assert (await auth_client.patch("/api/v1/settings", json={})).status_code == 401


async def test_bad_cookie_401(auth_client):
    auth_client.cookies.set("p2l_session", "junk")
    assert (await auth_client.get("/api/v1/categories")).status_code == 401


async def test_logout(auth_client):
    await login(auth_client)
    assert (await auth_client.post("/api/v1/auth/logout")).status_code == 200
    assert (await auth_client.get("/api/v1/categories")).status_code == 401


async def test_mode_none_allows_access(client):
    assert (await client.get("/api/v1/categories")).status_code == 200
    status = (await client.get("/api/v1/auth/status")).json()
    assert status["mode"] == "none" and status["authenticated"] is True
    assert (await login_none(client)).status_code == 200


async def login_none(c):
    return await c.post("/api/v1/auth/login", json={"username": "a", "password": "b"})


async def test_public_routes_open(auth_client):
    assert (await auth_client.get("/api/v1/health")).status_code == 200
    r = await auth_client.get("/api/v1/auth/status")
    assert r.json()["authenticated"] is False
    r = await auth_client.get("/api/v1/settings/public")
    assert r.status_code == 200
    body = r.json()
    assert body["auth.mode"] == "password"
    assert "scanner.min_length" in body
    assert "backup.keep" not in body and "trash.retention_days" not in body


async def test_change_password(auth_client):
    await login(auth_client)
    r = await auth_client.post(
        "/api/v1/auth/password", json={"current": "wrong-wrong", "new": "brand new pass"}
    )
    assert r.status_code == 422
    r = await auth_client.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "short"})
    assert r.status_code == 422
    r = await auth_client.post(
        "/api/v1/auth/password", json={"current": PASSWORD, "new": "brand new pass"}
    )
    assert r.status_code == 200
    assert (await login(auth_client, PASSWORD)).status_code == 401
    assert (await login(auth_client, "brand new pass")).status_code == 200


async def test_settings_api(auth_client, db):
    await login(auth_client)
    assert (await auth_client.get("/api/v1/settings")).json()["backup.keep"] == 14
    r = await auth_client.patch("/api/v1/settings", json={"backup.keep": 3})
    assert r.status_code == 200 and r.json()["backup.keep"] == 3
    r = await auth_client.patch("/api/v1/settings", json={"bogus": 1})
    assert r.status_code == 422 and r.json()["fields"] == {"bogus": "unknown setting"}
    r = await auth_client.patch("/api/v1/settings", json={"auth.mode": "none"})
    assert r.json()["auth.mode"] == "none"
    assert (await auth_client.get("/api/v1/categories")).status_code == 200
    await set_settings(db, {"auth.mode": "password"})
