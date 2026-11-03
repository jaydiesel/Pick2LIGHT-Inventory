from typing import Annotated, Any

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pick2light.backup import service as svc
from pick2light.backup.service import BackupInfo
from pick2light.errors import NotFound, ValidationFailed

router = APIRouter(tags=["backups"])


class BackupList(BaseModel):
    backup_dir: str
    backups: list[BackupInfo]
    last: dict[str, Any] | None


def _dir(request: Request):
    d = request.app.state.settings.backup_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(request: Request, name: str):
    path = _dir(request) / svc.check_name(name)
    if not path.exists():
        raise NotFound(f"Backup {name} not found")
    return path


@router.get("/backups")
async def list_backups(request: Request) -> BackupList:
    d = _dir(request)
    return BackupList(backup_dir=str(d), backups=svc.list_backups(d), last=svc.read_last(d))


@router.post("/backups")
async def backup_now(request: Request) -> BackupInfo:
    return await svc.create_backup(request.app.state.settings)


@router.get("/backups/{name}")
async def download(name: str, request: Request) -> FileResponse:
    return FileResponse(_file(request, name), media_type="application/gzip", filename=name)


@router.post("/backups/upload", status_code=201)
async def upload(request: Request, file: Annotated[UploadFile, File()]) -> BackupInfo:
    name = svc.check_name(file.filename or "")
    dest = _dir(request) / name
    if dest.exists():
        raise ValidationFailed({"file": "A backup with this name already exists"})
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    return next(b for b in svc.list_backups(dest.parent) if b.name == name)


@router.post("/backups/{name}/restore", status_code=204)
async def restore(name: str, request: Request) -> Response:
    await svc.restore_backup(request.app.state.settings, _file(request, name), request.app.state)
    return Response(status_code=204)
