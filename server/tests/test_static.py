import httpx
import pytest


@pytest.fixture
async def web_client(settings, db, tmp_path):
    from pick2light.app import create_app
    from pick2light.db import get_db

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>')
    (dist / "assets" / "app.js").write_text("console.log(1)")
    settings.web_dist = dist
    app = create_app(settings)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_spa_fallback_serves_index(web_client):
    r = await web_client.get("/items/5")
    assert r.status_code == 200 and '<div id="app">' in r.text


async def test_static_asset_served(web_client):
    r = await web_client.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


async def test_unknown_api_path_is_json_404(web_client):
    r = await web_client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


async def test_path_traversal_falls_back_to_index(web_client):
    r = await web_client.get("/../../etc/passwd")
    assert r.status_code in (200, 404) and "root:" not in r.text
