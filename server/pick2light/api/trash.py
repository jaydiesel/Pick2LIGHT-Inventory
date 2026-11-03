from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import trash as svc
from pick2light.core.trash import TrashEntry, TrashType

router = APIRouter(tags=["trash"])


@router.get("/trash")
async def list_trash(db: DB) -> list[TrashEntry]:
    return await svc.list_trash(db)


@router.post("/trash/{type_}/{row_id}/restore", status_code=204)
async def restore(type_: TrashType, row_id: int, db: DB) -> Response:
    await svc.restore(db, type_, row_id)
    return Response(status_code=204)
