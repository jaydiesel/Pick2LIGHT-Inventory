from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import items as svc
from pick2light.core import units as unit_svc
from pick2light.core.items import ItemIn, ItemOut, ItemPatch
from pick2light.core.units import UnitOut

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", status_code=201)
async def create_item(data: ItemIn, db: DB) -> ItemOut:
    return await svc.item_out(db, await svc.create_item(db, data))


@router.get("/{item_id}")
async def get_item(item_id: int, db: DB) -> ItemOut:
    return await svc.get_item_out(db, item_id)


@router.patch("/{item_id}")
async def update_item(item_id: int, data: ItemPatch, db: DB) -> ItemOut:
    return await svc.item_out(db, await svc.update_item(db, item_id, data))


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: int, db: DB) -> Response:
    await svc.delete_item(db, item_id)
    return Response(status_code=204)


@router.get("/{item_id}/units")
async def list_item_units(item_id: int, db: DB) -> list[UnitOut]:
    return [await unit_svc.unit_out(db, u) for u in await unit_svc.list_units(db, item_id)]
