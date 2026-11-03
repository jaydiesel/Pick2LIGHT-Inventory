"""Backups: database dump + attachments in one tar.gz, retention, restore and the scheduler.

A backup is `pick2light-YYYYMMDD-HHMM.tar.gz` holding `db.dump` (pg_dump custom format),
`attachments/` (without its `tmp/`) and `manifest.json`. Restore replaces the database and
the attachments directory; while it runs the app answers 503 (see the maintenance middleware).
"""

import asyncio
import contextlib
import io
import itertools
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import Iterator
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

NAME_RE = re.compile(r"pick2light-\d{8}-\d{4}(-\d+)?\.tar\.gz\Z")
LAST_BACKUP_FILE = "last_backup.json"
MAX_UPLOAD_BYTES = 2 * 1024**3
SLICE_SECONDS = 300


class BackupInfo(BaseModel):
    name: str
    size: int
    created_at: datetime


_LIBPQ_PARAMS = {
    "sslmode",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "sslcrl",
    "connect_timeout",
    "application_name",
    "options",
    "target_session_attrs",
}
_SSL_FLAGS = {"true": "require", "1": "require", "false": "disable", "0": "disable"}


def libpq_url(sqlalchemy_url: str) -> str:
    """The same URL without the SQLAlchemy driver suffix, for pg_dump / psql.

    asyncpg's `ssl=` becomes `sslmode=`; other asyncpg-only query parameters are dropped.
    """
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    query: dict[str, Any] = {}
    for key, value in url.query.items():
        if not isinstance(value, str):
            continue
        if key == "ssl":
            query["sslmode"] = _SSL_FLAGS.get(value.lower(), value)
        elif key in _LIBPQ_PARAMS:
            query[key] = value
    return url.set(query=query).render_as_string(hide_password=False)


def libpq_args(sqlalchemy_url: str) -> tuple[str, dict[str, str]]:
    """(URL without the password, environment carrying PGPASSWORD) for the pg_* tools."""
    url = make_url(libpq_url(sqlalchemy_url))
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return url._replace(password=None).render_as_string(hide_password=False), env


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


def _name_candidates() -> Iterator[str]:
    base = datetime.now().strftime("pick2light-%Y%m%d-%H%M")
    yield f"{base}.tar.gz"
    for n in itertools.count(2):
        yield f"{base}-{n}.tar.gz"


def place_file(src: Path, directory: Path, preferred: str | None = None) -> str:
    """Move `src` into `directory` under a free backup name, never overwriting a file.

    The name is claimed with an exclusive create, then the finished file replaces the claim.
    """
    names = _name_candidates()
    candidate = preferred if preferred and NAME_RE.match(preferred) else next(names)
    while True:
        try:
            os.close(os.open(directory / candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            candidate = next(names)
            continue
        os.replace(src, directory / candidate)
        return candidate


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


def _head_tail(text_: str, limit: int = 600) -> str:
    text_ = text_.strip()
    if len(text_) <= limit:
        return text_
    return f"{text_[: limit // 2]} ... {text_[-limit // 2 :]}"


async def _run(*argv: str, env: dict[str, str] | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=env
    )
    try:
        _, err = await proc.communicate()
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        raise InvalidOperation(
            f"{Path(argv[0]).name} failed: {_head_tail(err.decode(errors='replace'))}"
        )


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
        url, env = libpq_args(settings.database_url)
        await _run(
            "pg_dump",
            "--no-password",
            "--format=custom",
            "--no-owner",
            "--file",
            str(dump),
            url,
            env=env,
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
        name = await asyncio.to_thread(place_file, partial, directory)
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
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(dest, filter="data")


def _swap_attachments(extracted: Path, target: Path) -> None:
    """Replace `target` with `extracted/attachments`; undo the first step if the second fails."""
    new = extracted / "attachments"
    new.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_mount():
        _replace_contents(new, target)
        return
    old = target.with_name(f"{target.name}.old-{uuid.uuid4().hex}")
    had_old = target.exists()
    if had_old:
        os.replace(target, old)
    try:
        os.replace(new, target)
    except BaseException:
        if had_old:
            os.replace(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def _replace_contents(new: Path, target: Path) -> None:
    """In-place swap for a mount point or symlink: every rename stays inside `target`."""
    target.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged, old = target / f".restore-new-{token}", target / f".restore-old-{token}"
    staged.mkdir()
    old.mkdir()
    try:
        for child in new.iterdir():  # may cross filesystems (copy); nothing live is touched yet
            shutil.move(child, staged / child.name)
        moved: list[Path] = []
        try:
            for child in [c for c in target.iterdir() if c not in (staged, old)]:
                os.replace(child, old / child.name)
                moved.append(child)
            for child in list(staged.iterdir()):
                os.replace(child, target / child.name)
        except BaseException:
            for child in target.iterdir():
                if child not in (staged, old):
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
            for child in moved:
                os.replace(old / child.name, child)
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


async def restore_backup(settings: Settings, path: Path, app_state: Any) -> None:
    """Replace the database and attachments with the contents of the backup at `path`.

    The database is rebuilt from SQL in one transaction (schema `public` dropped and
    recreated), so a failure leaves the previous data in place. Callers must have
    committed and closed any session of their own: this also drops the app's pooled
    connections and terminates every other connection to the database first.
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
        url, env = libpq_args(settings.database_url)
        body, script = work / "body.sql", work / "restore.sql"
        await _run("pg_restore", "--no-owner", "-f", str(body), str(dump), env=env)
        await asyncio.to_thread(_build_script, body, script)
        await dispose_engines()
        await _terminate_other_backends(settings.database_url)
        await _run(
            "psql",
            "-w",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "--single-transaction",
            "-f",
            str(script),
            url,
            env=env,
        )
        try:
            await asyncio.to_thread(upgrade_database, settings.database_url)
        except Exception as exc:
            raise InvalidOperation(
                f"Database restored but migrating it to the current version failed: "
                f"{_head_tail(str(exc))}"
            ) from exc
        await asyncio.to_thread(_swap_attachments, work, data_dir / "attachments")
    finally:
        app_state.maintenance = False
        await asyncio.to_thread(shutil.rmtree, work, True)


def _build_script(body: Path, script: Path) -> None:
    with script.open("wb") as out:
        out.write(b"DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n")
        with body.open("rb") as src:
            shutil.copyfileobj(src, out)


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
        name = await asyncio.to_thread(place_file, part, directory, base)
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
    """Run a backup at the configured time every day until `stop` is set.

    Sleeps in slices and re-reads the schedule after each, so changes apply promptly.
    """
    anchor = datetime.now()
    while not stop.is_set():
        try:
            schedule, keep = await _read_schedule(settings)
        except Exception:
            log.exception("could not read backup settings")
            schedule, keep = "03:00", 14
        now = datetime.now()
        remaining = (next_run(schedule, anchor) - now).total_seconds()
        if remaining > 0:
            anchor = now
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), min(SLICE_SECONDS, remaining))
            continue
        try:
            info = await create_backup(settings)
            prune(_backup_dir(settings), keep)
            log.info("backup created: %s", info.name)
        except Exception:
            log.exception("scheduled backup failed")
        # Never fire twice for the same minute.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 61)
        anchor = datetime.now()
