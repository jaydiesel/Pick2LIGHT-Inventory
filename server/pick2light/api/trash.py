from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import trash as svc
from pick2light.core.trash import TrashEntry, TrashType

router = APIRouter(prefix="/trash", tags=["trash"])


@router.get("")
async def list_trash(db: DB) -> list[TrashEntry]:
    return await svc.list_trash(db)


@router.post("/{type}/{row_id}/restore", status_code=204)
async def restore(type: TrashType, row_id: int, db: DB) -> Response:
    await svc.restore(db, type, row_id)
    return Response(status_code=204)
