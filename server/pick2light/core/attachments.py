"""Photos, datasheets and documents stored on disk or linked by URL (spec §3.2 `attachment`)."""

import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import NotFound, ValidationFailed
from pick2light.models import Attachment, Category, Item, Location, LogEntry, Unit

OwnerType = Literal["item", "unit", "location", "log_entry", "category"]
Kind = Literal["photo", "datasheet", "document", "other"]
MAX_BYTES = 50 * 1024 * 1024
_OWNERS: dict[str, Any] = {
    "item": Item,
    "unit": Unit,
    "location": Location,
    "log_entry": LogEntry,
    "category": Category,
}


class LinkIn(BaseModel):
    owner_type: OwnerType
    owner_id: int
    kind: Kind = "datasheet"
    url: str = Field(min_length=1)
    filename: str | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_type: str
    owner_id: int
    kind: str
    filename: str
    content_type: str | None
    size_bytes: int | None
    sha256: str | None
    url: str | None


async def _check_owner(db: AsyncSession, owner_type: str, owner_id: int) -> None:
    model = _OWNERS.get(owner_type)
    row = await db.get(model, owner_id) if model else None
    if row is None or getattr(row, "deleted_at", None) is not None:
        raise NotFound(f"{owner_type.replace('_', ' ').capitalize()} {owner_id} not found")


def attachment_path(att: Attachment, root: Path) -> Path:
    if not att.storage_path:
        raise NotFound("This attachment is a link, not a stored file")
    return root / att.storage_path


def _safe_name(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name.strip()
    return base[:300] or "file"


async def save_upload(
    db: AsyncSession,
    *,
    root: Path,
    owner_type: str,
    owner_id: int,
    kind: str,
    filename: str,
    content_type: str | None,
    stream: AsyncIterator[bytes],
    max_bytes: int = MAX_BYTES,
) -> Attachment:
    await _check_owner(db, owner_type, owner_id)
    tmp_dir = root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / uuid.uuid4().hex
    digest, size = hashlib.sha256(), 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in stream:
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationFailed(
                        {"file": f"File is larger than {max_bytes // (1024 * 1024) or max_bytes} MB"}
                    )
                digest.update(chunk)
                fh.write(chunk)
        sha = digest.hexdigest()
        rel = f"{sha[:2]}/{sha}"
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            tmp.unlink()
        else:
            os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    att = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        filename=_safe_name(filename),
        content_type=content_type,
        size_bytes=size,
        sha256=sha,
        storage_path=rel,
    )
    db.add(att)
    await db.flush()
    return att


async def add_link(
    db: AsyncSession, *, owner_type: str, owner_id: int, kind: str, url: str, filename: str | None = None
) -> Attachment:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValidationFailed({"url": "Must start with http:// or https://"})
    await _check_owner(db, owner_type, owner_id)
    name = filename or _safe_name(url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]) or url
    att = Attachment(owner_type=owner_type, owner_id=owner_id, kind=kind, filename=name, url=url)
    db.add(att)
    await db.flush()
    return att


async def get_attachment(db: AsyncSession, attachment_id: int) -> Attachment:
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise NotFound(f"Attachment {attachment_id} not found")
    return att


async def list_attachments(db: AsyncSession, owner_type: str, owner_id: int) -> list[Attachment]:
    return list(
        await db.scalars(
            select(Attachment)
            .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
            .order_by(Attachment.id)
        )
    )


async def delete_attachment(db: AsyncSession, attachment_id: int, *, root: Path) -> None:
    att = await get_attachment(db, attachment_id)
    sha, path = att.sha256, att.storage_path
    await db.delete(att)
    await db.flush()
    if path and sha:
        others = await db.scalar(select(func.count()).select_from(Attachment).where(Attachment.sha256 == sha))
        if not others:
            (root / path).unlink(missing_ok=True)
