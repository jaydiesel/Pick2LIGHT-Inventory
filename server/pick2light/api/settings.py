from typing import Any

from fastapi import APIRouter

from pick2light.api.deps import DB, RequireAuth
from pick2light.core import settings as registry

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/public")
async def get_public(db: DB) -> dict[str, Any]:
    return {k: v for k, v in (await registry.get_all(db)).items() if registry.is_public(k)}


@router.get("", dependencies=[RequireAuth])
async def get_settings(db: DB) -> dict[str, Any]:
    return await registry.get_all(db)


@router.patch("", dependencies=[RequireAuth])
async def patch_settings(values: dict[str, Any], db: DB) -> dict[str, Any]:
    return await registry.set_settings(db, values)
