"""Attachments: uploaded files kept on disk (content-addressed) or links to external URLs.

Files live at `<root>/<sha[:2]>/<sha>`; identical uploads share one file, which is removed
only when the last row referencing it goes. `root` is `data_dir / "attachments"`.
Services flush but never commit; the request-scoped session commits.
"""

import asyncio
import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from pick2light.core.categories import get_category
from pick2light.core.items import get_item
from pick2light.core.locations import get_location
from pick2light.core.units import get_unit
from pick2light.core.urls import is_http_url
from pick2light.errors import NotFound, ValidationFailed
from pick2light.models import Attachment, LogEntry
from pick2light.models.files import ATTACHMENT_KINDS, ATTACHMENT_OWNER_TYPES

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TOO_LARGE = "File is larger than 50 MB"

# Content types the browser may display from the app's origin. Anything else (SVG, HTML,
# XML, ...) is always sent as a download, so an upload cannot run script on our origin.
INLINE_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
    }
)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class AttachmentOut(BaseModel):
    id: int
    owner_type: str
    owner_id: int
    kind: str
    filename: str
    content_type: str | None
    size_bytes: int | None
    sha256: str | None
    url: str | None
    created_at: datetime


def attachment_out(att: Attachment) -> AttachmentOut:
    return AttachmentOut.model_validate(att, from_attributes=True)


def safe_filename(name: str | None, default: str = "file") -> str:
    """The last path component of `name` (either separator style), without control characters."""
    last = _CONTROL_CHARS.sub("", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    if last in ("", ".", ".."):
        return default
    return last[:255]


def is_inline(content_type: str | None) -> bool:
    return (content_type or "").split(";")[0].strip().lower() in INLINE_TYPES


def attachment_path(att: Attachment, *, root: Path) -> Path:
    if att.storage_path is None:
        raise NotFound(f"Attachment {att.id} is a link and has no file")
    return root / att.storage_path


async def _check_owner(db: AsyncSession, owner_type: str, owner_id: int) -> None:
    if owner_type not in ATTACHMENT_OWNER_TYPES:
        raise ValidationFailed(
            {"owner_type": f"Must be one of {', '.join(ATTACHMENT_OWNER_TYPES)}"}
        )
    if owner_type == "item":
        await get_item(db, owner_id)
    elif owner_type == "unit":
        await get_unit(db, owner_id)
    elif owner_type == "location":
        await get_location(db, owner_id)
    elif owner_type == "category":
        await get_category(db, owner_id)
    elif await db.get(LogEntry, owner_id) is None:
        raise NotFound(f"Log entry {owner_id} not found")


def _check_kind(kind: str) -> None:
    if kind not in ATTACHMENT_KINDS:
        raise ValidationFailed({"kind": f"Must be one of {', '.join(ATTACHMENT_KINDS)}"})


async def save_upload(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: int,
    kind: str,
    filename: str,
    content_type: str | None,
    stream: AsyncIterator[bytes],
    root: Path,
    max_bytes: int | None = None,
) -> Attachment:
    limit = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    _check_kind(kind)
    await _check_owner(db, owner_type, owner_id)

    tmp_dir = root / "tmp"
    await asyncio.to_thread(tmp_dir.mkdir, parents=True, exist_ok=True)
    tmp = tmp_dir / uuid.uuid4().hex
    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in stream:
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed({"file": TOO_LARGE})
                digest.update(chunk)
                await asyncio.to_thread(out.write, chunk)
        sha = digest.hexdigest()
        # Held until this transaction ends: a concurrent delete of the same content then
        # waits, and sees our row, before deciding whether the file is still needed.
        await _lock_content(db, sha)
        rel = f"{sha[:2]}/{sha}"
        dest = root / rel
        await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
        if dest.exists():
            await asyncio.to_thread(tmp.unlink)
        else:
            await asyncio.to_thread(os.replace, tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    att = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        filename=safe_filename(filename),
        content_type=(content_type or "application/octet-stream")[:255],
        size_bytes=size,
        sha256=sha,
        storage_path=rel,
    )
    db.add(att)
    await db.flush()
    return att


async def add_link(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: int,
    kind: str,
    url: str,
    filename: str | None = None,
) -> Attachment:
    _check_kind(kind)
    url = url.strip()
    if not is_http_url(url):
        raise ValidationFailed({"url": "Must be an http:// or https:// URL"})
    await _check_owner(db, owner_type, owner_id)
    parts = urlsplit(url)
    default = safe_filename(unquote(parts.path), default=parts.hostname or "link")
    att = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        filename=safe_filename(filename, default=default),
        url=url,
    )
    db.add(att)
    await db.flush()
    return att


async def get_attachment(db: AsyncSession, attachment_id: int) -> Attachment:
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise NotFound(f"Attachment {attachment_id} not found")
    return att


async def list_attachments(db: AsyncSession, owner_type: str, owner_id: int) -> list[Attachment]:
    result = await db.scalars(
        select(Attachment)
        .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
        .order_by(Attachment.id)
    )
    return list(result)


def _lock_key(sha: str) -> object:
    return func.hashtextextended(sha, 0)


async def _lock_content(db: AsyncSession, sha: str) -> None:
    """Transaction-scoped lock serialising uploads and deletes of identical content."""
    await db.execute(select(func.pg_advisory_xact_lock(_lock_key(sha))))


_cleanup_tasks: set[asyncio.Task[None]] = set()


async def _unlink_if_unreferenced(
    bind: AsyncEngine | AsyncConnection, sha: str, path: Path
) -> None:
    """Remove the file unless a committed row still uses it.

    Runs after the deleting transaction committed, under the same content lock the
    uploads take, so an upload that reused the file is either already committed (seen
    here) or waits until the file is gone and writes it afresh.
    """
    engine = bind if isinstance(bind, AsyncEngine) else None
    conn_cm = engine.connect() if engine else None
    conn = await conn_cm.__aenter__() if conn_cm else bind
    assert isinstance(conn, AsyncConnection)
    try:
        await conn.execute(select(func.pg_advisory_lock(_lock_key(sha))))
        try:
            count = await conn.scalar(
                select(func.count()).select_from(Attachment).where(Attachment.sha256 == sha)
            )
            if not count:
                await asyncio.to_thread(path.unlink, missing_ok=True)
        finally:
            await conn.execute(select(func.pg_advisory_unlock(_lock_key(sha))))
            await conn.commit()
    finally:
        if conn_cm:
            await conn_cm.__aexit__(None, None, None)


def _schedule_unlinks(session: object) -> None:
    from sqlalchemy.orm import Session

    assert isinstance(session, Session)
    pending: list[tuple[AsyncEngine | AsyncConnection, str, Path]] = session.info.pop(
        "pending_unlinks", []
    )
    for bind, sha, path in pending:
        task = asyncio.get_running_loop().create_task(_unlink_if_unreferenced(bind, sha, path))
        _cleanup_tasks.add(task)
        task.add_done_callback(_cleanup_tasks.discard)


def _drop_unlinks(session: object, *_: object) -> None:
    from sqlalchemy.orm import Session

    assert isinstance(session, Session)
    session.info.pop("pending_unlinks", None)


async def finish_pending_unlinks() -> None:
    """Wait for file cleanups started by committed deletes (used by tests and shutdown)."""
    while _cleanup_tasks:
        await asyncio.gather(*list(_cleanup_tasks), return_exceptions=True)


def _defer_unlink(db: AsyncSession, sha: str, path: Path) -> None:
    info = db.sync_session.info
    if not info.get("unlink_hooks"):
        event.listen(db.sync_session, "after_commit", _schedule_unlinks)
        event.listen(db.sync_session, "after_rollback", _drop_unlinks)
        info["unlink_hooks"] = True
    assert db.bind is not None
    info.setdefault("pending_unlinks", []).append((db.bind, sha, path))


async def delete_attachment(db: AsyncSession, attachment_id: int, *, root: Path) -> None:
    """Delete the row. Its file is removed after commit, unless another row shares it.

    A rolled-back delete therefore never costs the file.
    """
    att = await get_attachment(db, attachment_id)
    sha = att.sha256
    path = attachment_path(att, root=root) if att.storage_path else None
    if sha is not None:
        await _lock_content(db, sha)
    await db.delete(att)
    await db.flush()
    if sha is not None and path is not None:
        _defer_unlink(db, sha, path)
