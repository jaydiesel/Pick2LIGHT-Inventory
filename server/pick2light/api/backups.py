from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pick2light.api.deps import DB
from pick2light.backup import service
from pick2light.backup.service import BackupInfo
from pick2light.config import Settings
from pick2light.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/backups", tags=["backups"])


class BackupList(BaseModel):
    backups: list[BackupInfo]
    backup_dir: str


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _existing(settings: Settings, name: str) -> Path:
    if not service.NAME_RE.match(name):
        raise ValidationFailed({"name": "Not a backup file name"})
    path = Path(str(settings.backup_dir)) / name
    if not path.is_file():
        raise NotFound(f"Backup {name} not found")
    return path


@router.get("")
async def list_backups(request: Request) -> BackupList:
    settings = _settings(request)
    return BackupList(
        backups=service.list_backups(Path(str(settings.backup_dir))),
        backup_dir=str(settings.backup_dir),
    )


@router.post("")
async def run_backup(request: Request) -> BackupInfo:
    return await service.create_backup(_settings(request))


@router.post("/upload")
async def upload(request: Request, file: UploadFile) -> BackupInfo:
    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    return await service.save_upload(_settings(request), file.filename, chunks())


@router.post("/{name:path}/restore", status_code=204)
async def restore(name: str, request: Request, db: DB) -> Response:
    settings = _settings(request)
    path = _existing(settings, name)
    # The restore needs exclusive locks: release this request's own transaction first.
    await db.commit()
    await db.close()
    await service.restore_backup(settings, path, request.app.state)
    return Response(status_code=204)


@router.get("/{name:path}")
async def download(name: str, request: Request) -> FileResponse:
    path = _existing(_settings(request), name)
    return FileResponse(path, media_type="application/gzip", filename=name)
