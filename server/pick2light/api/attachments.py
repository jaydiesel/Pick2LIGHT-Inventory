from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from pick2light.api.deps import DB
from pick2light.core import attachments as svc
from pick2light.core.attachments import AttachmentOut

router = APIRouter(prefix="/attachments", tags=["attachments"])

OwnerType = Literal["item", "unit", "location", "log_entry", "category"]
Kind = Literal["photo", "datasheet", "document", "other"]
CHUNK = 64 * 1024


def attachments_root(request: Request) -> Path:
    return Path(request.app.state.settings.data_dir) / "attachments"


Root = Annotated[Path, Depends(attachments_root)]


class LinkIn(BaseModel):
    owner_type: OwnerType
    owner_id: int
    kind: Kind
    url: str
    filename: str | None = None


async def _read(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(CHUNK):
        yield chunk


@router.post("", status_code=201)
async def upload(
    db: DB,
    root: Root,
    file: Annotated[UploadFile, File()],
    owner_type: Annotated[OwnerType, Form()],
    owner_id: Annotated[int, Form()],
    kind: Annotated[Kind, Form()],
) -> AttachmentOut:
    att = await svc.save_upload(
        db,
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        filename=file.filename or "file",
        content_type=file.content_type,
        stream=_read(file),
        root=root,
    )
    return svc.attachment_out(att)


@router.post("/link", status_code=201)
async def link(data: LinkIn, db: DB) -> AttachmentOut:
    att = await svc.add_link(db, **data.model_dump())
    return svc.attachment_out(att)


@router.get("")
async def list_for_owner(db: DB, owner_type: OwnerType, owner_id: int) -> list[AttachmentOut]:
    return [svc.attachment_out(a) for a in await svc.list_attachments(db, owner_type, owner_id)]


@router.get("/{attachment_id}/file", response_model=None)
async def download(attachment_id: int, db: DB, root: Root) -> Response:
    att = await svc.get_attachment(db, attachment_id)
    if att.url is not None:
        return RedirectResponse(att.url)
    inline = svc.is_inline(att.content_type)
    return FileResponse(
        svc.attachment_path(att, root=root),
        media_type=att.content_type if inline else "application/octet-stream",
        filename=att.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete(attachment_id: int, db: DB, root: Root) -> Response:
    await svc.delete_attachment(db, attachment_id, root=root)
    return Response(status_code=204)
