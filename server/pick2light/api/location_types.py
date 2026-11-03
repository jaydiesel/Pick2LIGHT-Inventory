from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from pick2light.api.deps import DB
from pick2light.errors import NotFound
from pick2light.models import LocationType

router = APIRouter(prefix="/location-types", tags=["location-types"])


class LocationTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = None


class LocationTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = None


class LocationTypeOut(LocationTypeIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


async def _get(db: DB, location_type_id: int) -> LocationType:
    location_type = await db.get(LocationType, location_type_id)
    if location_type is None:
        raise NotFound(f"Location type {location_type_id} not found")
    return location_type


@router.get("")
async def list_location_types(db: DB) -> list[LocationTypeOut]:
    rows = await db.scalars(select(LocationType).order_by(LocationType.name, LocationType.id))
    return [LocationTypeOut.model_validate(r) for r in rows]


@router.post("", status_code=201)
async def create_location_type(data: LocationTypeIn, db: DB) -> LocationTypeOut:
    location_type = LocationType(**data.model_dump())
    db.add(location_type)
    await db.flush()
    return LocationTypeOut.model_validate(location_type)


@router.patch("/{location_type_id}")
async def update_location_type(
    location_type_id: int, data: LocationTypePatch, db: DB
) -> LocationTypeOut:
    location_type = await _get(db, location_type_id)
    for name, value in data.model_dump(exclude_unset=True).items():
        if name == "name" and value is None:
            continue
        setattr(location_type, name, value)
    await db.flush()
    return LocationTypeOut.model_validate(location_type)


@router.delete("/{location_type_id}", status_code=204)
async def delete_location_type(location_type_id: int, db: DB) -> Response:
    await db.delete(await _get(db, location_type_id))
    await db.flush()
    return Response(status_code=204)
