from fastapi import APIRouter
from sqlalchemy import text

from pick2light import __version__
from pick2light.api.deps import DB

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DB) -> dict:
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    status = "ok" if database == "ok" else "degraded"
    return {"status": status, "database": database, "version": __version__}
