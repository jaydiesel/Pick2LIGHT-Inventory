from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import locations as svc
from pick2light.core.locations import LocationIn, LocationNode, LocationOut, LocationPatch, MoveIn

router = APIRouter(tags=["locations"])


@router.get("/locations/tree")
async def location_tree(db: DB) -> list[LocationNode]:
    return await svc.tree(db)


@router.post("/locations", status_code=201)
async def create_location(data: LocationIn, db: DB) -> LocationOut:
    return await svc.to_out(db, await svc.create_location(db, data))


@router.get("/locations/{location_id}")
async def get_location(location_id: int, db: DB) -> LocationOut:
    return await svc.to_out(db, await svc.get_location(db, location_id))


@router.patch("/locations/{location_id}")
async def update_location(location_id: int, data: LocationPatch, db: DB) -> LocationOut:
    return await svc.to_out(db, await svc.update_location(db, location_id, data))


@router.post("/locations/{location_id}/move")
async def move_location(location_id: int, data: MoveIn, db: DB) -> LocationOut:
    return await svc.to_out(db, await svc.move_location(db, location_id, data.parent_id))


@router.delete("/locations/{location_id}", status_code=204)
async def delete_location(location_id: int, db: DB) -> Response:
    await svc.delete_location(db, location_id)
    return Response(status_code=204)
