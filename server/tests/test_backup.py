import json
import os
from datetime import datetime
from pathlib import Path

from factories import make_category, make_item
from sqlalchemy import delete, select

from pick2light.backup.service import create_backup, list_backups, next_run, prune, restore_backup
from pick2light.config import Settings
from pick2light.models import Barcode, Item


def touch(d: Path, name: str, mtime: float) -> None:
    p = d / name
    p.write_bytes(b"x")
    os.utime(p, (mtime, mtime))


def test_next_run_today_and_tomorrow():
    now = datetime(2026, 11, 3, 2, 0)
    assert next_run("03:00", now) == datetime(2026, 11, 3, 3, 0)
    assert next_run("01:30", now) == datetime(2026, 11, 4, 1, 30)
    assert next_run("02:00", now) == datetime(2026, 11, 4, 2, 0)


def test_prune_keeps_newest(tmp_path):
    for i, name in enumerate(
        [
            "pick2light-20261101-0300.tar.gz",
            "pick2light-20261102-0300.tar.gz",
            "pick2light-20261103-0300.tar.gz",
        ]
    ):
        touch(tmp_path, name, 1_000_000 + i)
    removed = prune(tmp_path, keep=2)
    assert removed == ["pick2light-20261101-0300.tar.gz"]
    assert [b.name for b in list_backups(tmp_path)] == [
        "pick2light-20261103-0300.tar.gz",
        "pick2light-20261102-0300.tar.gz",
    ]


def test_prune_ignores_foreign_files(tmp_path):
    touch(tmp_path, "holiday-photos.tar.gz", 1)
    touch(tmp_path, "pick2light-20261101-0300.tar.gz", 2)
    assert prune(tmp_path, keep=0) == ["pick2light-20261101-0300.tar.gz"]
    assert (tmp_path / "holiday-photos.tar.gz").exists()


async def test_backup_name_traversal_rejected(client):
    for name in ("evil.tar.gz", "..pick2light-20261101-0300.tar.gz", "pick2light-2026.tar.gz"):
        r = await client.get(f"/api/v1/backups/{name}")
        assert r.status_code == 422, name


async def test_backup_and_restore_roundtrip(committed_db, database_url, tmp_path):
    from types import SimpleNamespace

    settings = Settings(database_url=database_url, data_dir=tmp_path / "data", secret_key="x")
    att = settings.attachments_dir / "ab" / "abcdef"
    att.parent.mkdir(parents=True)
    att.write_bytes(b"datasheet")
    async with committed_db() as s:
        item = await make_item(s, await make_category(s, "Cells"), "30Q")
        await s.commit()
        item_id = item.id
    info = await create_backup(settings)
    assert info.name.startswith("pick2light-") and (settings.backup_dir / info.name).exists()
    last = json.loads((settings.backup_dir / "last_backup.json").read_text())
    assert last["ok"] is True and last["file"] == info.name
    async with committed_db() as s:
        await s.execute(delete(Barcode))
        await s.execute(delete(Item))
        await s.commit()
    att.unlink()
    state = SimpleNamespace(maintenance=False)
    await restore_backup(settings, settings.backup_dir / info.name, state)
    assert state.maintenance is False
    async with committed_db() as s:
        assert (await s.scalar(select(Item.name).where(Item.id == item_id))) == "30Q"
    assert att.read_bytes() == b"datasheet"


async def test_maintenance_returns_503_except_health(app, client):
    app.state.maintenance = True
    r = await client.get("/api/v1/categories")
    assert r.status_code == 503 and r.json()["error"] == "maintenance"
    assert (await client.get("/api/v1/health")).status_code == 200


async def test_health_reports_failed_backup(client, settings):
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "last_backup.json").write_text(
        json.dumps({"at": "2026-11-03T03:00:00", "ok": False, "error": "disk full"})
    )
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "degraded" and body["backup"] == {"last_at": "2026-11-03T03:00:00", "ok": False}


async def test_backups_api_lists_dir(client, settings):
    r = await client.get("/api/v1/backups")
    assert (
        r.status_code == 200
        and r.json()["backup_dir"] == str(settings.backup_dir)
        and r.json()["backups"] == []
    )


def test_reset_db_requires_flag(monkeypatch):
    from typer.testing import CliRunner

    from pick2light import cli
    from pick2light.config import get_settings

    monkeypatch.delenv("P2L_ALLOW_RESET", raising=False)
    get_settings.cache_clear()
    result = CliRunner().invoke(cli.app, ["reset-db", "--yes"])
    get_settings.cache_clear()
    assert result.exit_code != 0 and "P2L_ALLOW_RESET" in result.output


def test_restore_requires_yes(tmp_path):
    from typer.testing import CliRunner

    from pick2light import cli

    result = CliRunner().invoke(cli.app, ["restore", str(tmp_path / "x.tar.gz")])
    assert result.exit_code != 0
