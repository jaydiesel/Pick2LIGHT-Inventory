"""Locations: a tree of rooms, cabinets and drawers, each with a scannable code."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import code_exists, register_barcode, remove_barcodes_for
from pick2light.core.sku import ensure_unique_code
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Location, LocationType

LightChildren = Literal["inherit", "on", "off"]


class LocationRef(BaseModel):
    id: int
    name: str
    code: str


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    location_type_id: int | None = None
    code: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    light_children: LightChildren = "inherit"


class LocationPatch(BaseModel):
    """Partial update; moving to another parent goes through `move_location`."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_type_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    light_children: LightChildren | None = None
    grid_row: int | None = None
    grid_col: int | None = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    location_type_id: int | None
    name: str
    code: str
    notes: str | None
    photo_attachment_id: int | None
    light_children: str
    grid_row: int | None
    grid_col: int | None
    created_at: datetime
    updated_at: datetime
    path: list[LocationRef]
    type_name: str | None


class LocationNode(BaseModel):
    id: int
    name: str
    code: str
    parent_id: int | None
    location_type_id: int | None
    type_name: str | None
    children: list[LocationNode] = []


async def get_location(db: AsyncSession, location_id: int) -> Location:
    location = await db.get(Location, location_id)
    if location is None or location.deleted_at is not None:
        raise NotFound(f"Location {location_id} not found")
    return location


async def _code_taken(db: AsyncSession, code: str) -> bool:
    """A code is taken by a barcode or by any location row, deleted ones included."""
    if await code_exists(db, code):
        return True
    return await db.scalar(select(Location.id).where(Location.code == code).limit(1)) is not None


async def _check_type(db: AsyncSession, location_type_id: int | None) -> None:
    if location_type_id is not None and await db.get(LocationType, location_type_id) is None:
        raise ValidationFailed({"location_type_id": "Location type not found"})


async def _check_parent(db: AsyncSession, parent_id: int | None) -> None:
    if parent_id is not None:
        await get_location(db, parent_id)


async def _next_code(db: AsyncSession) -> str:
    seq = (await db.execute(text("SELECT nextval('location_code_seq')"))).scalar_one()
    return await ensure_unique_code(f"LOC-{seq:04d}", lambda c: _code_taken(db, c))


async def create_location(db: AsyncSession, data: LocationIn) -> Location:
    await _check_parent(db, data.parent_id)
    await _check_type(db, data.location_type_id)
    code = data.code.strip() if data.code else ""
    if code:
        if await _code_taken(db, code):
            raise Conflict(f"Code {code!r} is already in use")
    else:
        code = await _next_code(db)
    location = Location(
        parent_id=data.parent_id,
        location_type_id=data.location_type_id,
        name=data.name,
        code=code,
        notes=data.notes,
        light_children=data.light_children,
    )
    db.add(location)
    await db.flush()
    await register_barcode(db, code, "location", location.id, "location_code")
    return location


async def update_location(db: AsyncSession, location_id: int, data: LocationPatch) -> Location:
    location = await get_location(db, location_id)
    changes = data.model_dump(exclude_unset=True)
    for required in ("name", "light_children"):
        if required in changes and changes[required] is None:
            del changes[required]
    if "location_type_id" in changes:
        await _check_type(db, changes["location_type_id"])
    new_code = changes.pop("code", None)
    for key, value in changes.items():
        setattr(location, key, value)
    if new_code is not None and new_code.strip() != location.code:
        new_code = new_code.strip()
        if not new_code:
            raise ValidationFailed({"code": "must not be empty"})
        if await _code_taken(db, new_code):
            raise Conflict(f"Code {new_code!r} is already in use")
        await remove_barcodes_for(db, "location", location.id, kind="location_code")
        location.code = new_code
        await db.flush()
        await register_barcode(db, new_code, "location", location.id, "location_code")
    await db.flush()
    await db.refresh(location)  # picks up the server-side updated_at
    return location


async def subtree_ids(db: AsyncSession, location_id: int) -> list[int]:
    """The location and all its non-deleted descendants."""
    result = await db.execute(
        text(
            "WITH RECURSIVE sub AS ("
            " SELECT id FROM location WHERE id = :id AND deleted_at IS NULL"
            " UNION ALL"
            " SELECT l.id FROM location l JOIN sub ON l.parent_id = sub.id"
            " WHERE l.deleted_at IS NULL"
            ") SELECT id FROM sub ORDER BY id"
        ),
        {"id": location_id},
    )
    return [row[0] for row in result]


async def move_location(db: AsyncSession, location_id: int, new_parent_id: int | None) -> Location:
    location = await get_location(db, location_id)
    await _check_parent(db, new_parent_id)
    if new_parent_id is not None and new_parent_id in await subtree_ids(db, location_id):
        raise Conflict("A location cannot be moved into itself or one of its own sub-locations")
    location.parent_id = new_parent_id
    await db.flush()
    await db.refresh(location)
    return location


async def delete_location(db: AsyncSession, location_id: int) -> None:
    """Soft-delete; the row keeps its code but the code stops scanning.

    Refusing while stock or units are present is added with stock (Task 8).
    """
    location = await get_location(db, location_id)
    child = await db.scalar(
        select(Location.id)
        .where(Location.parent_id == location_id, Location.deleted_at.is_(None))
        .limit(1)
    )
    if child is not None:
        raise Conflict("Location still has sub-locations; delete or move them first")
    location.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "location", location_id)
    await db.flush()


async def location_path(db: AsyncSession, location_id: int) -> list[LocationRef]:
    """Root-first chain of ancestors ending with the location itself."""
    result = await db.execute(
        text(
            "WITH RECURSIVE up AS ("
            " SELECT id, name, code, parent_id, 0 AS depth FROM location WHERE id = :id"
            " UNION ALL"
            " SELECT l.id, l.name, l.code, l.parent_id, up.depth + 1"
            " FROM location l JOIN up ON l.id = up.parent_id"
            ") SELECT id, name, code FROM up ORDER BY depth DESC"
        ),
        {"id": location_id},
    )
    return [LocationRef(id=r.id, name=r.name, code=r.code) for r in result]


async def location_out(db: AsyncSession, location: Location) -> LocationOut:
    type_name = None
    if location.location_type_id is not None:
        location_type = await db.get(LocationType, location.location_type_id)
        type_name = location_type.name if location_type else None
    return LocationOut.model_validate(
        {
            **{k: getattr(location, k) for k in LocationOut.model_fields if hasattr(location, k)},
            "path": await location_path(db, location.id),
            "type_name": type_name,
        }
    )


async def tree(db: AsyncSession) -> list[LocationNode]:
    """All non-deleted locations as a nested forest, siblings ordered by name."""
    rows = await db.execute(
        select(Location, LocationType.name)
        .outerjoin(LocationType, Location.location_type_id == LocationType.id)
        .where(Location.deleted_at.is_(None))
        .order_by(Location.name, Location.id)
    )
    nodes = {
        loc.id: LocationNode(
            id=loc.id,
            name=loc.name,
            code=loc.code,
            parent_id=loc.parent_id,
            location_type_id=loc.location_type_id,
            type_name=type_name,
        )
        for loc, type_name in rows
    }
    roots: list[LocationNode] = []
    for node in nodes.values():  # already in name order
        parent = nodes.get(node.parent_id) if node.parent_id is not None else None
        (parent.children if parent else roots).append(node)
    return roots
