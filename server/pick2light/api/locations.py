from fastapi import APIRouter, Response
from pydantic import BaseModel

from pick2light.api.deps import DB
from pick2light.core import locations as svc
from pick2light.core.locations import LocationIn, LocationNode, LocationOut, LocationPatch

router = APIRouter(prefix="/locations", tags=["locations"])


class MoveIn(BaseModel):
    parent_id: int | None = None


@router.get("/tree")
async def location_tree(db: DB) -> list[LocationNode]:
    return await svc.tree(db)


@router.post("", status_code=201)
async def create_location(data: LocationIn, db: DB) -> LocationOut:
    return await svc.location_out(db, await svc.create_location(db, data))


@router.get("/{location_id}")
async def get_location(location_id: int, db: DB) -> LocationOut:
    return await svc.location_out(db, await svc.get_location(db, location_id))


@router.patch("/{location_id}")
async def update_location(location_id: int, data: LocationPatch, db: DB) -> LocationOut:
    return await svc.location_out(db, await svc.update_location(db, location_id, data))


@router.post("/{location_id}/move")
async def move_location(location_id: int, data: MoveIn, db: DB) -> LocationOut:
    return await svc.location_out(db, await svc.move_location(db, location_id, data.parent_id))


@router.delete("/{location_id}", status_code=204)
async def delete_location(location_id: int, db: DB) -> Response:
    await svc.delete_location(db, location_id)
    return Response(status_code=204)
