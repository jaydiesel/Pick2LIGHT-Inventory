from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import units as svc
from pick2light.core.units import UnitIn, UnitOut, UnitPatch

router = APIRouter(tags=["units"])


@router.post("/units", status_code=201)
async def create_unit(data: UnitIn, db: DB) -> UnitOut:
    unit = await svc.create_unit(db, data)
    return await svc.get_unit_out(db, unit.id)


@router.get("/units/{unit_id}")
async def get_unit(unit_id: int, db: DB) -> UnitOut:
    return await svc.get_unit_out(db, unit_id)


@router.patch("/units/{unit_id}")
async def update_unit(unit_id: int, data: UnitPatch, db: DB) -> UnitOut:
    await svc.update_unit(db, unit_id, data)
    return await svc.get_unit_out(db, unit_id)


@router.delete("/units/{unit_id}", status_code=204)
async def delete_unit(unit_id: int, db: DB) -> Response:
    await svc.delete_unit(db, unit_id)
    return Response(status_code=204)
