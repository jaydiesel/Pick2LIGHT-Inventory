from pathlib import Path

import httpx
import pytest

from pick2light.app import create_app
from pick2light.config import Settings


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa</html>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    return root


def make_client(tmp_path: Path, web_dist: Path | None):
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        data_dir=tmp_path,
        secret_key="s",
        web_dist=web_dist,
    )
    app = create_app(settings)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return app, client


async def test_spa_fallback_serves_index(tmp_path: Path, dist: Path):
    _, c = make_client(tmp_path, dist)
    async with c:
        for path in ("/", "/items/5", "/settings"):
            r = await c.get(path)
            assert r.status_code == 200
            assert r.text == "<html>spa</html>"


async def test_existing_file_served(tmp_path: Path, dist: Path):
    _, c = make_client(tmp_path, dist)
    async with c:
        r = await c.get("/assets/app.js")
        assert r.status_code == 200
        assert r.text == "console.log(1)"


async def test_api_unknown_path_stays_json_404(tmp_path: Path, dist: Path):
    _, c = make_client(tmp_path, dist)
    async with c:
        for path in ("/api/v1/nope", "/api/nope"):
            r = await c.get(path)
            assert r.status_code == 404
            assert r.json()["error"] == "not_found"


async def test_path_traversal_does_not_escape(tmp_path: Path, dist: Path):
    _, c = make_client(tmp_path, dist)
    async with c:
        r = await c.get("/%2e%2e/secret.txt")
        assert "nope" not in r.text
        assert r.text == "<html>spa</html>"


async def test_no_web_dist_means_no_spa(tmp_path: Path):
    _, c = make_client(tmp_path, None)
    async with c:
        assert (await c.get("/items/5")).status_code == 404


async def test_static_gets_503_during_maintenance(tmp_path: Path, dist: Path):
    app, c = make_client(tmp_path, dist)
    app.state.maintenance = True
    async with c:
        r = await c.get("/items/5")
        assert r.status_code == 503
        assert r.json()["error"] == "maintenance"
