from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from pick2light.api.deps import DB
from pick2light.core import attachments as svc
from pick2light.core.attachments import AttachmentOut, Kind, LinkIn, OwnerType

router = APIRouter(tags=["attachments"])
INLINE_TYPES = ("application/pdf", "image/")


def _root(request: Request):
    return request.app.state.settings.attachments_dir


@router.post("/attachments", status_code=201)
async def upload(
    request: Request,
    db: DB,
    file: Annotated[UploadFile, File()],
    owner_type: Annotated[OwnerType, Form()],
    owner_id: Annotated[int, Form()],
    kind: Annotated[Kind, Form()] = "other",
) -> AttachmentOut:
    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    att = await svc.save_upload(
        db,
        root=_root(request),
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        filename=file.filename or "file",
        content_type=file.content_type,
        stream=chunks(),
    )
    return AttachmentOut.model_validate(att)


@router.post("/attachments/link", status_code=201)
async def add_link(data: LinkIn, db: DB) -> AttachmentOut:
    att = await svc.add_link(
        db,
        owner_type=data.owner_type,
        owner_id=data.owner_id,
        kind=data.kind,
        url=data.url,
        filename=data.filename,
    )
    return AttachmentOut.model_validate(att)


@router.get("/attachments")
async def list_attachments(owner_type: OwnerType, owner_id: int, db: DB) -> list[AttachmentOut]:
    return [AttachmentOut.model_validate(a) for a in await svc.list_attachments(db, owner_type, owner_id)]


@router.get("/attachments/{attachment_id}/file", response_model=None)
async def download(attachment_id: int, request: Request, db: DB) -> Response:
    att = await svc.get_attachment(db, attachment_id)
    if att.url:
        return RedirectResponse(att.url)
    inline = (att.content_type or "").startswith(INLINE_TYPES)
    return FileResponse(
        svc.attachment_path(att, _root(request)),
        media_type=att.content_type or "application/octet-stream",
        filename=att.filename,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete(attachment_id: int, request: Request, db: DB) -> Response:
    await svc.delete_attachment(db, attachment_id, root=_root(request))
    return Response(status_code=204)
