from fastapi import APIRouter, Request
from sqlalchemy import text

from pick2light import __version__
from pick2light.api.deps import DB
from pick2light.backup.service import read_last

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, db: DB) -> dict:
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    last = read_last(request.app.state.settings.backup_dir)
    backup = {"last_at": last.get("at"), "ok": bool(last.get("ok"))} if last else None
    healthy = database == "ok" and (backup is None or backup["ok"])
    return {
        "status": "ok" if healthy else "degraded",
        "database": database,
        "backup": backup,
        "maintenance": bool(getattr(request.app.state, "maintenance", False)),
        "version": __version__,
    }
