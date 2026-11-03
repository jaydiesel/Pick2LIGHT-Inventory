from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import categories as svc
from pick2light.core.categories import LocationTypeIn, LocationTypeOut, LocationTypePatch

router = APIRouter(tags=["locations"])


@router.get("/location-types")
async def list_location_types(db: DB) -> list[LocationTypeOut]:
    return [LocationTypeOut.model_validate(t) for t in await svc.list_location_types(db)]


@router.post("/location-types", status_code=201)
async def create_location_type(data: LocationTypeIn, db: DB) -> LocationTypeOut:
    return LocationTypeOut.model_validate(await svc.create_location_type(db, data))


@router.patch("/location-types/{type_id}")
async def update_location_type(type_id: int, data: LocationTypePatch, db: DB) -> LocationTypeOut:
    return LocationTypeOut.model_validate(await svc.update_location_type(db, type_id, data))


@router.delete("/location-types/{type_id}", status_code=204)
async def delete_location_type(type_id: int, db: DB) -> Response:
    await svc.delete_location_type(db, type_id)
    return Response(status_code=204)
