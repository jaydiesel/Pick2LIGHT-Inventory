import asyncio
import io
import json
import os
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner

from pick2light import cli
from pick2light.app import create_app
from pick2light.backup import service
from pick2light.config import Settings, get_settings
from pick2light.core.settings import set_settings
from pick2light.db import get_db
from tests.factories import make_category, make_item


def _touch(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"x")


def test_libpq_url_drops_driver() -> None:
    assert service.libpq_url("postgresql+asyncpg://u:p@h:5/db") == "postgresql://u:p@h:5/db"


def test_next_run_today_and_tomorrow() -> None:
    now = datetime(2026, 11, 3, 2, 0)
    assert service.next_run("03:00", now) == datetime(2026, 11, 3, 3, 0)
    assert service.next_run("03:00", datetime(2026, 11, 3, 3, 0)) == datetime(2026, 11, 4, 3, 0)
    assert service.next_run("01:30", now) == datetime(2026, 11, 4, 1, 30)


def test_prune_keeps_newest(tmp_path: Path) -> None:
    names = [f"pick2light-2026110{d}-0300.tar.gz" for d in range(1, 6)]
    for i, n in enumerate(names):
        _touch(tmp_path, n)
        os.utime(tmp_path / n, (1_000_000 + i, 1_000_000 + i))
    removed = service.prune(tmp_path, 2)
    assert sorted(removed) == sorted(names[:3])
    assert [b.name for b in service.list_backups(tmp_path)] == [names[4], names[3]]


def test_prune_ignores_foreign_files(tmp_path: Path) -> None:
    _touch(tmp_path, "notes.txt")
    _touch(tmp_path, "pick2light-20261101-0300.tar.gz")
    _touch(tmp_path, "pick2light-20261102-0300.tar.gz")
    assert service.prune(tmp_path, 1) == ["pick2light-20261101-0300.tar.gz"]
    assert (tmp_path / "notes.txt").exists()


async def test_backup_name_traversal_rejected(client: httpx.AsyncClient) -> None:
    for bad in ("../x", "..%2Fx", "x.tar.gz", "pick2light-20261101-0300.tar.gz/../../etc"):
        r = await client.get(f"/api/v1/backups/{bad}")
        assert r.status_code in (404, 422), bad
    r = await client.get("/api/v1/backups/..%2Fx")
    assert r.status_code == 422 and r.json()["error"] == "validation"
    r = await client.post("/api/v1/backups/..%2Fx/restore")
    assert r.status_code == 422


async def test_unknown_backup_is_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/backups/pick2light-20200101-0000.tar.gz")
    assert r.status_code == 404


async def test_list_backups_route_includes_dir(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    r = await client.get("/api/v1/backups")
    assert r.status_code == 200
    assert r.json() == {"backups": [], "backup_dir": str(settings.backup_dir)}


def _tar(members: list[tuple[str, bytes | None, str]]) -> bytes:
    """members: (name, data, kind) with kind file|symlink|hardlink."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                payload = data or b""
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            else:
                info.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
    return buf.getvalue()


@pytest.mark.parametrize(
    "members",
    [
        [("db.dump", b"x", "file")],  # no manifest
        [("manifest.json", b"{}", "file"), ("/abs", b"x", "file")],
        [("manifest.json", b"{}", "file"), ("../evil", b"x", "file")],
        [("manifest.json", b"{}", "file"), ("a/../../evil", b"x", "file")],
        [("manifest.json", b"{}", "file"), ("l", None, "symlink")],
        [("manifest.json", b"{}", "file"), ("h", None, "hardlink")],
    ],
)
async def test_upload_rejects_bad_archives(
    client: httpx.AsyncClient, settings: Settings, members: list
) -> None:
    r = await client.post(
        "/api/v1/backups/upload",
        files={"file": ("pick2light-20261101-0300.tar.gz", _tar(members), "application/gzip")},
    )
    assert r.status_code == 422, r.text
    assert service.list_backups(settings.backup_dir) == []
    assert not any(settings.backup_dir.iterdir())


async def test_upload_rejects_non_gzip(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/backups/upload", files={"file": ("a.tar.gz", b"hello")})
    assert r.status_code == 422


async def test_upload_accepts_valid_and_generates_name(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    data = _tar([("manifest.json", b"{}", "file"), ("db.dump", b"x", "file")])
    r = await client.post("/api/v1/backups/upload", files={"file": ("../my backup.tgz", data)})
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert service.NAME_RE.match(name)
    assert (settings.backup_dir / name).read_bytes() == data
    r = await client.post(
        "/api/v1/backups/upload",
        files={"file": ("pick2light-20200102-0304.tar.gz", data)},
    )
    assert r.json()["name"] == "pick2light-20200102-0304.tar.gz"
    d = await client.get("/api/v1/backups/pick2light-20200102-0304.tar.gz")
    assert d.status_code == 200 and d.content == data


async def test_maintenance_returns_503_except_health(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.maintenance = True
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    for path in ("/api/v1/items", "/api/docs", "/", "/assets/x.js"):
        r = await client.get(path)
        assert r.status_code == 503, path
        assert r.json() == {"error": "maintenance"}
    app.state.maintenance = False
    assert (await client.get("/api/v1/categories")).status_code == 200


async def test_health_reports_failed_backup(client: httpx.AsyncClient, settings: Settings) -> None:
    assert (await client.get("/api/v1/health")).json()["backup"] is None
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "last_backup.json").write_text(
        json.dumps({"at": "2026-11-03T03:00:00+00:00", "ok": False, "error": "boom"})
    )
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "degraded"
    assert body["backup"] == {"last_at": "2026-11-03T03:00:00+00:00", "ok": False}
    (settings.backup_dir / "last_backup.json").write_text(
        json.dumps({"at": "2026-11-03T03:00:00+00:00", "ok": True, "file": "f"})
    )
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "ok" and body["backup"]["ok"] is True


def test_reset_db_requires_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()
    monkeypatch.setenv("P2L_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("P2L_SECRET_KEY", "k")
    monkeypatch.delenv("P2L_ALLOW_RESET", raising=False)
    get_settings.cache_clear()
    called: list[str] = []
    monkeypatch.setattr(cli, "_reset_schema", lambda url: called.append(url))
    try:
        r = runner.invoke(cli.app, ["reset-db", "--yes"])
        assert r.exit_code != 0 and "P2L_ALLOW_RESET" in r.output
        monkeypatch.setenv("P2L_ALLOW_RESET", "1")
        get_settings.cache_clear()
        r = runner.invoke(cli.app, ["reset-db"])
        assert r.exit_code != 0 and "--yes" in r.output
        assert called == []
        r = runner.invoke(cli.app, ["reset-db", "--yes"])
        assert r.exit_code == 0, r.output
        assert len(called) == 1
    finally:
        get_settings.cache_clear()


def test_restore_cli_requires_yes(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"x")
    r = CliRunner().invoke(cli.app, ["restore", str(f)])
    assert r.exit_code != 0


@pytest_asyncio.fixture
async def real_app(
    settings: Settings, committed_db: async_sessionmaker[AsyncSession]
) -> AsyncIterator[FastAPI]:
    """An app whose requests use their own committed sessions (so restore can lock)."""
    application = create_app(settings)

    async def _db() -> AsyncIterator[AsyncSession]:
        async with committed_db() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = _db
    async with committed_db() as s:
        await set_settings(s, {"auth.mode": "none"})
        await s.commit()
    yield application


async def test_backup_and_restore_roundtrip(
    real_app: FastAPI,
    committed_db: async_sessionmaker[AsyncSession],
    settings: Settings,
    engine,
) -> None:
    att = Path(settings.data_dir) / "attachments"
    (att / "ab").mkdir(parents=True)
    (att / "ab" / "abcdef").write_text("attachment-content")
    (att / "tmp").mkdir()
    (att / "tmp" / "partial").write_text("junk")
    async with committed_db() as s:
        cat = await make_category(s, "Cat")
        item = await make_item(s, cat, "Resistor")
        await s.commit()
        item_id = item.id

    transport = httpx.ASGITransport(app=real_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/backups")
        assert r.status_code == 200, r.text
        name = r.json()["name"]
        assert service.NAME_RE.match(name)
        with tarfile.open(settings.backup_dir / name) as tar:
            names = tar.getnames()
        assert "db.dump" in names and "manifest.json" in names
        assert "attachments/ab/abcdef" in names
        assert not any(n.startswith("attachments/tmp") for n in names)
        last = json.loads((settings.backup_dir / "last_backup.json").read_text())
        assert last["ok"] is True and last["file"] == name

        # Destroy the item and its attachment file.
        async with committed_db() as s:
            await s.execute(text("DELETE FROM item"))
            await s.commit()
        (att / "ab" / "abcdef").unlink()

        # A leftover open transaction must not wedge the restore.
        idle = await engine.connect()
        await idle.execute(text("SELECT * FROM item"))

        r = await asyncio.wait_for(c.post(f"/api/v1/backups/{name}/restore"), 60)
        assert r.status_code == 204, r.text
        assert real_app.state.maintenance is False
        await idle.invalidate()  # its backend was terminated by the restore
    await engine.dispose()

    async with committed_db() as s:
        assert (
            await s.execute(text("SELECT name FROM item WHERE id = :i"), {"i": item_id})
        ).scalar_one() == "Resistor"
    assert (att / "ab" / "abcdef").read_text() == "attachment-content"
    assert not (att / "tmp" / "partial").exists()


async def test_restore_rejects_newer_revision(settings: Settings, tmp_path: Path) -> None:
    from types import SimpleNamespace

    from pick2light.errors import InvalidOperation

    archive = tmp_path / "pick2light-20261101-0300.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in (
            ("manifest.json", json.dumps({"version": "x", "alembic_revision": "zzzz_future"})),
            ("db.dump", "x"),
        ):
            raw = data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    state = SimpleNamespace(maintenance=False)
    with pytest.raises(InvalidOperation):
        await service.restore_backup(settings, archive, state)
    assert state.maintenance is False
