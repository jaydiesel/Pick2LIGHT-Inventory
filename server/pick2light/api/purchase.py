from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import purchase as svc
from pick2light.core.purchase import PurchaseSourceIn, PurchaseSourceOut, PurchaseSourcePatch

router = APIRouter(tags=["purchase sources"])


@router.get("/items/{item_id}/purchase-sources")
async def list_sources(item_id: int, db: DB) -> list[PurchaseSourceOut]:
    return [svc.source_out(s) for s in await svc.list_sources(db, item_id)]


@router.post("/items/{item_id}/purchase-sources", status_code=201)
async def create_source(item_id: int, data: PurchaseSourceIn, db: DB) -> PurchaseSourceOut:
    return svc.source_out(await svc.create_source(db, item_id, data))


@router.patch("/purchase-sources/{source_id}")
async def update_source(source_id: int, data: PurchaseSourcePatch, db: DB) -> PurchaseSourceOut:
    return svc.source_out(await svc.update_source(db, source_id, data))


@router.delete("/purchase-sources/{source_id}", status_code=204)
async def delete_source(source_id: int, db: DB) -> Response:
    await svc.delete_source(db, source_id)
    return Response(status_code=204)
