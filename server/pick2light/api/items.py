from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import items as svc
from pick2light.core.items import ItemIn, ItemOut, ItemPatch
from pick2light.core.units import UnitOut, get_unit_out, list_units

router = APIRouter(tags=["items"])


@router.post("/items", status_code=201)
async def create_item(data: ItemIn, db: DB) -> ItemOut:
    item = await svc.create_item(db, data)
    return await svc.get_item_out(db, item.id)


@router.get("/items/{item_id}")
async def get_item(item_id: int, db: DB) -> ItemOut:
    return await svc.get_item_out(db, item_id)


@router.patch("/items/{item_id}")
async def update_item(item_id: int, data: ItemPatch, db: DB) -> ItemOut:
    await svc.update_item(db, item_id, data)
    return await svc.get_item_out(db, item_id)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: int, db: DB) -> Response:
    await svc.delete_item(db, item_id)
    return Response(status_code=204)


@router.get("/items/{item_id}/units")
async def item_units(item_id: int, db: DB) -> list[UnitOut]:
    return [await get_unit_out(db, u.id) for u in await list_units(db, item_id)]
