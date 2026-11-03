from typing import Any

from fastapi import APIRouter

from pick2light.api.deps import DB
from pick2light.core import settings as svc

router = APIRouter(tags=["settings"])
public_router = APIRouter(tags=["settings"])


@public_router.get("/settings/public")
async def public(db: DB) -> dict[str, Any]:
    return await svc.public_settings(db)


@router.get("/settings")
async def get_all(db: DB) -> dict[str, Any]:
    return await svc.get_all(db)


@router.patch("/settings")
async def update(values: dict[str, Any], db: DB) -> dict[str, Any]:
    return await svc.set_settings(db, values)
