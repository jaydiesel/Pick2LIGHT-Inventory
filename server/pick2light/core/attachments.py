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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def delete_attachment(db: AsyncSession, attachment_id: int, *, root: Path) -> None:
    """Delete the row; the file goes too unless another row shares its content."""
    att = await get_attachment(db, attachment_id)
    sha = att.sha256
    path = attachment_path(att, root=root) if att.storage_path else None
    await db.delete(att)
    await db.flush()
    if path is None:
        return
    shared = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.sha256 == sha)
    )
    if not shared:
        await asyncio.to_thread(path.unlink, missing_ok=True)
