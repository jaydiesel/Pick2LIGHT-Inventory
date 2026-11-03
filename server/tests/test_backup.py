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
from pick2light.errors import InvalidOperation
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
        assert r.json() == {"error": "maintenance", "message": "Restore in progress"}
    assert (await client.get("/api/v1/health")).json()["maintenance"] is True
    app.state.maintenance = False
    assert (await client.get("/api/v1/health")).json()["maintenance"] is False
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


def test_name_re_rejects_trailing_newline() -> None:
    assert service.NAME_RE.match("pick2light-20261101-0300.tar.gz")
    assert not service.NAME_RE.match("pick2light-20261101-0300.tar.gz\n")


def test_libpq_args_keep_password_out_of_url() -> None:
    url, env = service.libpq_args("postgresql+asyncpg://u:sekrit@h:5/db?ssl=require&timeout=5")
    assert "sekrit" not in url and env["PGPASSWORD"] == "sekrit"
    assert "sslmode=require" in url and "timeout" not in url and "ssl=" not in url


@pytest_asyncio.fixture
async def scratch_url(database_url: str) -> AsyncIterator[str]:
    """A private database, so restores here cannot disturb the shared test database."""
    from sqlalchemy import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    name = f"p2l_scratch_{os.getpid()}"
    url = make_url(database_url)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def _scalar(url: str, sql: str):
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(url)
    try:
        async with eng.connect() as conn:
            return (await conn.execute(text(sql))).scalar()
    finally:
        await eng.dispose()


async def _exec(url: str, sql: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(url)
    try:
        async with eng.begin() as conn:
            await conn.execute(text(sql))
    finally:
        await eng.dispose()


async def test_restore_older_revision_backup(scratch_url: str, tmp_path: Path) -> None:
    from types import SimpleNamespace

    from alembic import command

    from pick2light.db import alembic_config, upgrade_database

    settings = Settings(database_url=scratch_url, data_dir=tmp_path, secret_key="k")
    await asyncio.to_thread(command.upgrade, alembic_config(scratch_url), "0009")
    await _exec(
        scratch_url,
        "INSERT INTO category (name, tracking_mode) VALUES ('C', 'bulk')",
    )
    info = await service.create_backup(settings)
    with tarfile.open(settings.backup_dir / info.name) as tar:
        member = tar.extractfile("manifest.json")
        assert member is not None and json.load(member)["alembic_revision"] == "0009"

    await asyncio.to_thread(upgrade_database, scratch_url)  # now at head (has label_template)
    await _exec(scratch_url, "DELETE FROM category")
    state = SimpleNamespace(maintenance=False)
    await asyncio.wait_for(
        service.restore_backup(settings, settings.backup_dir / info.name, state), 60
    )
    assert state.maintenance is False
    assert await _scalar(scratch_url, "SELECT name FROM category") == "C"
    assert await _scalar(scratch_url, "SELECT version_num FROM alembic_version") == "0010"
    assert await _scalar(scratch_url, "SELECT count(*) FROM label_template") > 0


async def test_failed_restore_leaves_data_and_clears_maintenance(
    scratch_url: str, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from pick2light.db import upgrade_database
    from pick2light.errors import InvalidOperation

    settings = Settings(database_url=scratch_url, data_dir=tmp_path, secret_key="k")
    await asyncio.to_thread(upgrade_database, scratch_url)
    await _exec(scratch_url, "INSERT INTO category (name, tracking_mode) VALUES ('Keep', 'bulk')")
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "orig").write_text("original")
    info = await service.create_backup(settings)

    # Corrupt the dump inside an otherwise valid archive.
    bad = tmp_path / "pick2light-20200101-0000.tar.gz"
    with tarfile.open(settings.backup_dir / info.name) as src, tarfile.open(bad, "w:gz") as dst:
        for m in src.getmembers():
            f = src.extractfile(m) if m.isfile() else None
            if m.name == "db.dump":
                payload = b"PGDMP-garbage" * 10
                m.size = len(payload)
                f = io.BytesIO(payload)
            dst.addfile(m, f)

    state = SimpleNamespace(maintenance=False)
    with pytest.raises(InvalidOperation):
        await asyncio.wait_for(service.restore_backup(settings, bad, state), 60)
    assert state.maintenance is False
    assert await _scalar(scratch_url, "SELECT name FROM category") == "Keep"
    assert (att / "orig").read_text() == "original"


async def test_scheduler_survives_failing_backup(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*a, **k):
        raise InvalidOperation("pg_dump failed: nope")

    async def sched(_settings):
        return "03:00", 1

    monkeypatch.setattr(service, "_create_backup", boom)
    monkeypatch.setattr(service, "_read_schedule", sched)
    monkeypatch.setattr(service, "next_run", lambda schedule, now: now)
    stop = asyncio.Event()
    task = asyncio.create_task(service.scheduler_loop(settings, stop))
    marker = settings.backup_dir / "last_backup.json"
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.05)
    assert json.loads(marker.read_text())["ok"] is False
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, 5)


async def test_upload_does_not_overwrite_existing(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    a = _tar([("manifest.json", b"{}", "file"), ("db.dump", b"a", "file")])
    b = _tar([("manifest.json", b"{}", "file"), ("db.dump", b"bb", "file")])
    name = "pick2light-20200102-0304.tar.gz"
    await client.post("/api/v1/backups/upload", files={"file": (name, a)})
    r = await client.post("/api/v1/backups/upload", files={"file": (name, b)})
    assert r.json()["name"] != name
    assert (settings.backup_dir / name).read_bytes() == a


async def test_upload_rejects_oversize_content_length(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/backups/upload",
        content=b"x",
        headers={
            "content-length": str(3 * 1024**3),
            "content-type": "multipart/form-data; boundary=x",
        },
    )
    assert r.status_code == 422


def test_swap_attachments_rolls_back_and_handles_symlink(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "attachments"
    target.mkdir()
    (target / "old").write_text("old")
    new_root = tmp_path / "work"
    (new_root / "attachments").mkdir(parents=True)
    (new_root / "attachments" / "new").write_text("new")
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("boom")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        service._swap_attachments(new_root, target)
    monkeypatch.setattr(os, "replace", real)
    assert (target / "old").read_text() == "old"

    # symlinked target: contents are replaced in place
    real_dir = tmp_path / "mnt"
    real_dir.mkdir()
    (real_dir / "old2").write_text("x")
    link = tmp_path / "linked"
    link.symlink_to(real_dir)
    service._swap_attachments(new_root, link)
    assert link.is_symlink()
    assert sorted(p.name for p in real_dir.iterdir()) == ["new"]


async def test_password_never_in_argv(
    scratch_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import make_url

    from pick2light.db import upgrade_database

    settings = Settings(database_url=scratch_url, data_dir=tmp_path, secret_key="k")
    await asyncio.to_thread(upgrade_database, scratch_url)
    seen: list[tuple[tuple, dict]] = []
    real = asyncio.create_subprocess_exec

    async def spy(*argv, **kw):
        seen.append((argv, kw))
        return await real(*argv, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    password = make_url(scratch_url).password
    info = await service.create_backup(settings)
    await service.restore_backup(
        settings, settings.backup_dir / info.name, SimpleNamespace(maintenance=False)
    )
    tools = {Path(argv[0]).name for argv, _ in seen}
    assert {"pg_dump", "pg_restore", "psql"} <= tools
    for argv, kw in seen:
        assert not any(f":{password}@" in a for a in argv)
        assert kw["env"]["PGPASSWORD"] == password
    for argv, _ in seen:
        if Path(argv[0]).name in ("pg_dump", "psql"):
            assert "--no-password" in argv or "-w" in argv


async def test_psql_failure_midway_keeps_original_data(
    scratch_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from pick2light.db import upgrade_database

    settings = Settings(database_url=scratch_url, data_dir=tmp_path, secret_key="k")
    await asyncio.to_thread(upgrade_database, scratch_url)
    await _exec(scratch_url, "INSERT INTO category (name) VALUES ('Keep')")
    info = await service.create_backup(settings)
    await _exec(scratch_url, "UPDATE category SET name = 'Current'")
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "orig").write_text("original")

    real_run = service._run

    async def run(*argv, **kw):
        await real_run(*argv, **kw)
        if Path(argv[0]).name == "pg_restore":  # inject a failing statement after the DROP
            body = Path(argv[argv.index("-f") + 1])
            body.write_text(body.read_text() + "\nSELECT 1/0;\n")

    monkeypatch.setattr(service, "_run", run)
    state = SimpleNamespace(maintenance=False)
    with pytest.raises(InvalidOperation) as err:
        await asyncio.wait_for(
            service.restore_backup(settings, settings.backup_dir / info.name, state), 60
        )
    assert str(tmp_path) not in err.value.message
    assert state.maintenance is False
    assert await _scalar(scratch_url, "SELECT name FROM category") == "Current"
    assert (att / "orig").read_text() == "original"


def test_place_file_removes_placeholder_on_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        service.place_file(tmp_path / "missing", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_in_place_swap_failure_loses_nothing(tmp_path: Path, monkeypatch) -> None:
    real_dir = tmp_path / "mnt"
    real_dir.mkdir()
    for n in "abc":
        (real_dir / n).write_text(n)
    link = tmp_path / "linked"
    link.symlink_to(real_dir)
    new_root = tmp_path / "work"
    (new_root / "attachments").mkdir(parents=True)
    (new_root / "attachments" / "x").write_text("x")
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("boom")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        service._swap_attachments(new_root, link)
    monkeypatch.setattr(os, "replace", real)
    assert sorted(p.name for p in real_dir.iterdir()) == ["a", "b", "c"]
    assert [(real_dir / n).read_text() for n in "abc"] == ["a", "b", "c"]


@pytest.mark.parametrize("rel", ["./data", "."])
def test_scrub_ignores_relative_data_dir(
    rel: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        database_url="postgresql+asyncpg://u@h/d", data_dir=Path(rel), secret_key="k"
    )
    msg = 'database "x" does not exist, see data/ or a.b'
    assert service._scrub(msg, settings) == msg


def test_scrub_replaces_absolute_paths(tmp_path: Path) -> None:
    data = tmp_path / "data"
    settings = Settings(database_url="postgresql+asyncpg://u@h/d", data_dir=data, secret_key="k")
    msg = f'could not open "{data}/tmp/x": denied; dir={data}; {data}x stays'
    out = service._scrub(msg, settings)
    assert '"<data_dir>/tmp/x"' in out and "dir=<data_dir>;" in out and f"{data}x stays" in out
