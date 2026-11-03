"""Database + attachment backups, retention and restore (spec §12)."""

import asyncio
import json
import logging
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
from pydantic import BaseModel

from pick2light import __version__
from pick2light.config import Settings
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed

log = logging.getLogger("pick2light.backup")
NAME_RE = re.compile(r"^pick2light-\d{8}-\d{4}(-\d+)?\.tar\.gz$")
LAST = "last_backup.json"


class BackupInfo(BaseModel):
    name: str
    size: int
    created_at: datetime


def libpq_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def check_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise ValidationFailed({"name": "Not a Pick2LIGHT backup file name"})
    return name


def _backup_dir(settings: Settings) -> Path:
    assert settings.backup_dir is not None
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    return settings.backup_dir


def _info(path: Path) -> BackupInfo:
    stat = path.stat()
    return BackupInfo(
        name=path.name, size=stat.st_size, created_at=datetime.fromtimestamp(stat.st_mtime).astimezone()
    )


def list_backups(directory: Path) -> list[BackupInfo]:
    if not directory.exists():
        return []
    files = [p for p in directory.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return [_info(p) for p in sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)]


def prune(directory: Path, keep: int) -> list[str]:
    removed = []
    for info in list_backups(directory)[max(keep, 0) :]:
        (directory / info.name).unlink(missing_ok=True)
        removed.append(info.name)
    return removed


def read_last(directory: Path) -> dict[str, Any] | None:
    path = directory / LAST
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def _write_last(directory: Path, **data: Any) -> None:
    (directory / LAST).write_text(json.dumps({"at": datetime.now().astimezone().isoformat(), **data}))


async def _run(*cmd: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise InvalidOperation(f"{cmd[0]} failed: {err.decode(errors='replace').strip()[:500]}")


async def _revision(url: str) -> str | None:
    conn = await asyncpg.connect(libpq_url(url))
    try:
        return await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    finally:
        await conn.close()


def _unique_name(directory: Path) -> str:
    base = f"pick2light-{datetime.now():%Y%m%d-%H%M}"
    name, n = f"{base}.tar.gz", 1
    while (directory / name).exists():
        n += 1
        name = f"{base}-{n}.tar.gz"
    return name


async def create_backup(settings: Settings) -> BackupInfo:
    directory = _backup_dir(settings)
    name = _unique_name(directory)
    try:
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            tmp_path = Path(tmp)
            dump = tmp_path / "db.dump"
            await _run(
                "pg_dump", "--format=custom", "--no-owner", f"--file={dump}", libpq_url(settings.database_url)
            )
            manifest = {
                "version": __version__,
                "created_at": datetime.now().astimezone().isoformat(),
                "alembic_revision": await _revision(settings.database_url),
            }
            (tmp_path / "manifest.json").write_text(json.dumps(manifest))
            partial = directory / f".{name}.partial"

            def _tar() -> None:
                with tarfile.open(partial, "w:gz") as tar:
                    tar.add(tmp_path / "manifest.json", arcname="manifest.json")
                    tar.add(dump, arcname="db.dump")
                    att = settings.attachments_dir
                    if att.exists():
                        tar.add(
                            att,
                            arcname="attachments",
                            filter=lambda ti: None if ti.name.startswith("attachments/tmp") else ti,
                        )

            await asyncio.to_thread(_tar)
            partial.rename(directory / name)
    except Exception as exc:
        _write_last(directory, ok=False, error=str(exc)[:500])
        raise
    _write_last(directory, ok=True, file=name)
    return _info(directory / name)


def _known_revisions() -> list[str]:
    from alembic.script import ScriptDirectory

    from pick2light.cli import _alembic_config

    script = ScriptDirectory.from_config(_alembic_config())
    return [rev.revision for rev in script.walk_revisions()]


async def _replace_database(url: str, dump: Path) -> None:
    """Empty the schema, then load the dump in one transaction (all or nothing)."""
    conn = await asyncpg.connect(libpq_url(url))
    try:
        await conn.execute("SET lock_timeout = '15s'")  # fail instead of waiting on a lingering connection
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()
    await _run(
        "pg_restore", "--single-transaction", "--exit-on-error", "--no-owner", "-d", libpq_url(url), str(dump)
    )


def _extract(archive: Path, dest: Path) -> dict[str, Any]:
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    manifest_file = dest / "manifest.json"
    if not manifest_file.exists() or not (dest / "db.dump").exists():
        raise InvalidOperation("This file is not a Pick2LIGHT backup")
    return json.loads(manifest_file.read_text())


def _swap_attachments(target: Path, restored: Path) -> None:
    staging = target.with_name(target.name + ".restoring")
    old = target.with_name(target.name + ".old")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    if restored.exists():
        shutil.copytree(restored, staging)
    else:
        staging.mkdir(parents=True)
    if target.exists():
        target.rename(old)
    staging.rename(target)
    shutil.rmtree(old, ignore_errors=True)


async def restore_backup(
    settings: Settings, path: Path, app_state: Any, *, safety_backup: bool = True
) -> None:
    """Replace the database and attachments with a backup.

    A safety backup of the current data is written first; if loading the chosen backup fails, the
    safety backup is put back. The caller must not hold an open transaction on this database.
    """
    if not path.exists():
        raise NotFound(f"Backup {path.name} not found")
    app_state.maintenance = True
    try:
        with tempfile.TemporaryDirectory(dir=_backup_dir(settings)) as tmp:
            tmp_path = Path(tmp)
            manifest = await asyncio.to_thread(_extract, path, tmp_path / "chosen")
            revision = manifest.get("alembic_revision")
            if revision and revision not in _known_revisions():
                raise InvalidOperation("This backup comes from a newer Pick2LIGHT version; update first")
            safety = await create_backup(settings) if safety_backup else None
            try:
                await _replace_database(settings.database_url, tmp_path / "chosen" / "db.dump")
            except Exception as exc:
                if safety is not None:
                    await asyncio.to_thread(
                        _extract, _backup_dir(settings) / safety.name, tmp_path / "safety"
                    )
                    await _replace_database(settings.database_url, tmp_path / "safety" / "db.dump")
                    raise InvalidOperation(
                        f"Restore failed and your previous data was put back: {exc}"
                    ) from exc
                raise
            await asyncio.to_thread(
                _swap_attachments, settings.attachments_dir, tmp_path / "chosen" / "attachments"
            )
        from pick2light.cli import run_migrations

        await asyncio.to_thread(run_migrations, settings.database_url)
    finally:
        app_state.maintenance = False


def next_run(schedule: str, now: datetime) -> datetime:
    hour, minute = (int(x) for x in schedule.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


async def scheduler_loop(settings: Settings, stop: asyncio.Event) -> None:
    """Run nightly backups at `backup.schedule`, keeping `backup.keep` files."""
    from pick2light.core.settings import get_setting
    from pick2light.db import make_engine, make_sessionmaker

    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    target: datetime | None = None
    current: str | None = None
    try:
        while not stop.is_set():
            async with sessions() as db:
                schedule = await get_setting(db, "backup.schedule")
                keep = await get_setting(db, "backup.keep")
            now = datetime.now()
            if target is None or schedule != current:
                target, current = next_run(schedule, now), schedule
            if now >= target:
                try:
                    info = await create_backup(settings)
                    prune(_backup_dir(settings), keep)
                    log.info("Backup written: %s", info.name)
                except Exception:
                    log.exception("Scheduled backup failed")
                target = next_run(schedule, datetime.now())
                continue
            try:  # re-check at least hourly so schedule changes apply
                await asyncio.wait_for(stop.wait(), timeout=min((target - now).total_seconds(), 3600))
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
