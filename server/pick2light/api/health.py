from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from pick2light import __version__
from pick2light.api.deps import DB
from pick2light.backup.service import read_last_backup

router = APIRouter(tags=["health"])


class BackupStatus(BaseModel):
    last_at: str | None
    ok: bool


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str
    backup: BackupStatus | None = None
    maintenance: bool = False


def _backup_status(request: Request) -> BackupStatus | None:
    directory = request.app.state.settings.backup_dir
    last = read_last_backup(Path(str(directory)))
    if last is None:
        return None
    at = last.get("at")
    return BackupStatus(last_at=at if isinstance(at, str) else None, ok=last.get("ok") is True)


@router.get("/health")
async def health(request: Request, db: DB) -> Health:
    backup = _backup_status(request)
    maint = bool(request.app.state.maintenance)
    backup_failed = backup is not None and not backup.ok
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return Health(
            status="degraded",
            database="error",
            version=__version__,
            backup=backup,
            maintenance=maint,
        )
    return Health(
        status="degraded" if backup_failed else "ok",
        database="ok",
        version=__version__,
        backup=backup,
        maintenance=maint,
    )
