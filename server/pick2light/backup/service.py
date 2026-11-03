"""Backups: database dump + attachments in one tar.gz, retention, restore and the scheduler.

A backup is `pick2light-YYYYMMDD-HHMM.tar.gz` holding `db.dump` (pg_dump custom format),
`attachments/` (without its `tmp/`) and `manifest.json`. Restore replaces the database and
the attachments directory; while it runs the app answers 503 (see the maintenance middleware).
"""

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from alembic.script import ScriptDirectory
from pydantic import BaseModel
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pick2light import __version__
from pick2light.config import Settings
from pick2light.core.settings import get_setting
from pick2light.db import alembic_config, dispose_engines, upgrade_database
from pick2light.errors import InvalidOperation, ValidationFailed

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^pick2light-\d{8}-\d{4}(-\d+)?\.tar\.gz$")
LAST_BACKUP_FILE = "last_backup.json"
MAX_UPLOAD_BYTES = 2 * 1024**3


class BackupInfo(BaseModel):
    name: str
    size: int
    created_at: datetime


def libpq_url(sqlalchemy_url: str) -> str:
    """The same URL without the SQLAlchemy driver suffix, for pg_dump / pg_restore."""
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _info(path: Path) -> BackupInfo:
    st = path.stat()
    return BackupInfo(
        name=path.name, size=st.st_size, created_at=datetime.fromtimestamp(st.st_mtime).astimezone()
    )


def list_backups(directory: Path) -> list[BackupInfo]:
    if not directory.is_dir():
        return []
    found = [_info(p) for p in directory.iterdir() if NAME_RE.match(p.name) and p.is_file()]
    return sorted(found, key=lambda b: (b.created_at, b.name), reverse=True)


def prune(directory: Path, keep: int) -> list[str]:
    """Delete all but the `keep` newest backups; only files matching the backup name."""
    removed = []
    for info in list_backups(directory)[max(keep, 0) :]:
        (directory / info.name).unlink(missing_ok=True)
        removed.append(info.name)
    return removed


def next_run(schedule: str, now: datetime) -> datetime:
    """Today at HH:MM when that is still ahead, else tomorrow."""
    hour, minute = (int(part) for part in schedule.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _backup_dir(settings: Settings) -> Path:
    assert settings.backup_dir is not None
    return settings.backup_dir


def new_backup_name(directory: Path) -> str:
    base = datetime.now().strftime("pick2light-%Y%m%d-%H%M")
    name, n = f"{base}.tar.gz", 1
    while (directory / name).exists():
        n += 1
        name = f"{base}-{n}.tar.gz"
    return name


def _write_last(directory: Path, data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{LAST_BACKUP_FILE}.{uuid.uuid4().hex}"
    tmp.write_text(json.dumps(data))
    os.replace(tmp, directory / LAST_BACKUP_FILE)


def read_last_backup(directory: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((directory / LAST_BACKUP_FILE).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def _run(*argv: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        detail = err.decode(errors="replace").strip()[-500:]
        raise InvalidOperation(f"{Path(argv[0]).name} failed: {detail}")


async def _current_revision(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    finally:
        await engine.dispose()


def _make_archive(dest: Path, dump: Path, attachments: Path, manifest: dict[str, Any]) -> None:
    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if info.name == "attachments/tmp" or info.name.startswith("attachments/tmp/"):
            return None
        return info if info.isfile() or info.isdir() else None

    with tarfile.open(dest, "w:gz") as tar:
        tar.add(dump, arcname="db.dump")
        if attachments.is_dir():
            tar.add(attachments, arcname="attachments", filter=keep)
        raw = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        info.mtime = int(datetime.now().timestamp())
        tar.addfile(info, io.BytesIO(raw))


async def create_backup(settings: Settings) -> BackupInfo:
    directory = _backup_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        info = await _create_backup(settings, directory)
    except Exception as exc:
        _write_last(
            directory,
            {"at": datetime.now().astimezone().isoformat(), "ok": False, "error": str(exc)},
        )
        raise
    _write_last(
        directory,
        {"at": datetime.now().astimezone().isoformat(), "ok": True, "file": info.name},
    )
    return info


async def _create_backup(settings: Settings, directory: Path) -> BackupInfo:
    revision = await _current_revision(settings.database_url)
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=directory) as work_name:
        work = Path(work_name)
        dump = work / "db.dump"
        await _run(
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--file",
            str(dump),
            libpq_url(settings.database_url),
        )
        manifest = {
            "version": __version__,
            "created_at": datetime.now().astimezone().isoformat(),
            "alembic_revision": revision,
        }
        partial = work / "backup.tar.gz"
        await asyncio.to_thread(
            _make_archive, partial, dump, Path(settings.data_dir) / "attachments", manifest
        )
        name = new_backup_name(directory)
        await asyncio.to_thread(os.replace, partial, directory / name)
    return _info(directory / name)


# --- archive validation -------------------------------------------------------------------


def validate_archive(path: Path) -> dict[str, Any]:
    """Check that `path` is a gzip tar that is safe to extract and has a manifest.

    Returns the parsed manifest. Raises ValidationFailed otherwise.
    """
    bad = ValidationFailed
    try:
        with tarfile.open(path, "r:gz") as tar:
            manifest: dict[str, Any] | None = None
            for member in tar:
                parts = PurePosixPath(member.name).parts
                if member.name.startswith("/") or ".." in parts or "\\" in member.name:
                    raise bad({"file": f"Unsafe path in archive: {member.name!r}"})
                if not (member.isfile() or member.isdir()):
                    raise bad({"file": f"Links and special files are not allowed: {member.name!r}"})
                if member.name == "manifest.json" and member.isfile():
                    handle = tar.extractfile(member)
                    assert handle is not None
                    loaded = json.loads(handle.read(1024 * 1024))
                    manifest = loaded if isinstance(loaded, dict) else {}
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        raise bad({"file": f"Not a valid backup archive: {exc}"}) from exc
    if manifest is None:
        raise bad({"file": "Archive has no manifest.json"})
    return manifest


# --- restore -------------------------------------------------------------------------------


def _ancestors_of_head() -> set[str]:
    script = ScriptDirectory.from_config(alembic_config())
    return {rev.revision for rev in script.walk_revisions()}


async def _terminate_other_backends(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
    finally:
        await engine.dispose()


def _extract(path: Path, dest: Path) -> None:
    validate_archive(path)
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(dest, filter="data")


def _swap_attachments(extracted: Path, target: Path) -> None:
    new = extracted / "attachments"
    new.mkdir(exist_ok=True)
    old = target.with_name(f"{target.name}.old-{uuid.uuid4().hex}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        os.replace(target, old)
    os.replace(new, target)
    shutil.rmtree(old, ignore_errors=True)


async def restore_backup(settings: Settings, path: Path, app_state: Any) -> None:
    """Replace the database and attachments with the contents of the backup at `path`.

    Callers must have committed and closed any session of their own: the restore needs
    exclusive locks, so this also drops the app's pooled connections and terminates every
    other connection to the database before running pg_restore.
    """
    manifest = await asyncio.to_thread(validate_archive, path)
    revision = manifest.get("alembic_revision")
    if not isinstance(revision, str) or revision not in await asyncio.to_thread(_ancestors_of_head):
        raise InvalidOperation(
            f"Backup was made by a newer or unknown schema revision ({revision}); "
            "update Pick2LIGHT before restoring it"
        )
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".restore-", dir=data_dir))
    app_state.maintenance = True
    try:
        await asyncio.to_thread(_extract, path, work)
        dump = work / "db.dump"
        if not dump.is_file():
            raise InvalidOperation("Backup contains no db.dump")
        await dispose_engines()
        await _terminate_other_backends(settings.database_url)
        await _run(
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "-d",
            libpq_url(settings.database_url),
            str(dump),
        )
        await asyncio.to_thread(_swap_attachments, work, data_dir / "attachments")
        await asyncio.to_thread(upgrade_database, settings.database_url)
    finally:
        app_state.maintenance = False
        await asyncio.to_thread(shutil.rmtree, work, True)


# --- upload ---------------------------------------------------------------------------------


async def save_upload(settings: Settings, filename: str | None, chunks: Any) -> BackupInfo:
    """Store an uploaded backup after validating it. `chunks` is an async byte iterator."""
    directory = _backup_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    part = directory / f".upload-{uuid.uuid4().hex}.part"
    try:
        size = 0
        with part.open("wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValidationFailed({"file": "File is larger than 2 GiB"})
                await asyncio.to_thread(out.write, chunk)
        await asyncio.to_thread(validate_archive, part)
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if NAME_RE.match(base) and not (directory / base).exists():
            name = base
        else:
            name = new_backup_name(directory)
        await asyncio.to_thread(os.replace, part, directory / name)
    finally:
        part.unlink(missing_ok=True)
    return _info(directory / name)


# --- scheduler -------------------------------------------------------------------------------


async def _read_schedule(settings: Settings) -> tuple[str, int]:
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await _schedule_from(db)
    finally:
        await engine.dispose()


async def _schedule_from(db: AsyncSession) -> tuple[str, int]:
    return str(await get_setting(db, "backup.schedule")), int(await get_setting(db, "backup.keep"))


async def scheduler_loop(settings: Settings, stop: asyncio.Event) -> None:
    """Run a backup at the configured time every day until `stop` is set."""
    while not stop.is_set():
        try:
            schedule, keep = await _read_schedule(settings)
        except Exception:
            log.exception("could not read backup settings")
            schedule, keep = "03:00", 14
        now = datetime.now()
        wait = (next_run(schedule, now) - now).total_seconds()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), wait)
        if stop.is_set():
            return
        try:
            _, keep = await _read_schedule(settings)
        except Exception:
            log.exception("could not read backup settings")
        try:
            info = await create_backup(settings)
            prune(_backup_dir(settings), keep)
            log.info("backup created: %s", info.name)
        except Exception:
            log.exception("scheduled backup failed")
        # Never fire twice for the same minute.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 61)
