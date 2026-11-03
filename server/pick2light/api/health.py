from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from pick2light import __version__
from pick2light.api.deps import DB

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str


@router.get("/health")
async def health(db: DB) -> Health:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return Health(status="degraded", database="error", version=__version__)
    return Health(status="ok", database="ok", version=__version__)
