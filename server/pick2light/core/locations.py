"""Location tree (spec §3.3)."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import register_barcode, remove_barcodes_for
from pick2light.core.sku import sanitize_code
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Location, LocationType

LightChildren = Literal["inherit", "on", "off"]


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    location_type_id: int | None = None
    code: str | None = Field(default=None, max_length=64)
    notes: str | None = None
    light_children: LightChildren = "inherit"
    grid_row: int | None = None
    grid_col: int | None = None


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_type_id: int | None = None
    code: str | None = Field(default=None, max_length=64)
    notes: str | None = None
    light_children: LightChildren | None = None
    grid_row: int | None = None
    grid_col: int | None = None
    photo_attachment_id: int | None = None


class MoveIn(BaseModel):
    parent_id: int | None


class LocationRef(BaseModel):
    id: int
    name: str
    code: str


class LocationOut(BaseModel):
    id: int
    name: str
    code: str
    parent_id: int | None
    location_type_id: int | None
    type_name: str | None
    notes: str | None
    photo_attachment_id: int | None
    light_children: str
    grid_row: int | None
    grid_col: int | None
    path: list[LocationRef]
    created_at: datetime
    updated_at: datetime


class LocationNode(BaseModel):
    id: int
    name: str
    code: str
    type_name: str | None
    children: list["LocationNode"] = []


async def _all(db: AsyncSession) -> dict[int, Location]:
    rows = await db.scalars(select(Location).where(Location.deleted_at.is_(None)))
    return {loc.id: loc for loc in rows}


async def get_location(db: AsyncSession, location_id: int) -> Location:
    loc = await db.get(Location, location_id)
    if loc is None or loc.deleted_at is not None:
        raise NotFound(f"Location {location_id} not found")
    return loc


def _chain(locs: dict[int, Location], location_id: int) -> list[Location]:
    out: list[Location] = []
    current: int | None = location_id
    seen: set[int] = set()
    while current is not None and current in locs and current not in seen:
        seen.add(current)
        out.append(locs[current])
        current = locs[current].parent_id
    return list(reversed(out))


def _descendants(locs: dict[int, Location], location_id: int) -> list[int]:
    children: dict[int | None, list[int]] = {}
    for loc in locs.values():
        children.setdefault(loc.parent_id, []).append(loc.id)
    out, stack = [], [location_id]
    while stack:
        lid = stack.pop()
        out.append(lid)
        stack.extend(children.get(lid, []))
    return out


async def location_path(db: AsyncSession, location_id: int) -> list[LocationRef]:
    locs = await _all(db)
    return [LocationRef(id=x.id, name=x.name, code=x.code) for x in _chain(locs, location_id)]


async def subtree_ids(db: AsyncSession, location_id: int) -> list[int]:
    await get_location(db, location_id)
    return _descendants(await _all(db), location_id)


async def _type_names(db: AsyncSession) -> dict[int, str]:
    return {t.id: t.name for t in await db.scalars(select(LocationType))}


async def to_out(db: AsyncSession, loc: Location) -> LocationOut:
    types = await _type_names(db)
    return LocationOut(
        id=loc.id,
        name=loc.name,
        code=loc.code,
        parent_id=loc.parent_id,
        location_type_id=loc.location_type_id,
        type_name=types.get(loc.location_type_id) if loc.location_type_id else None,
        notes=loc.notes,
        photo_attachment_id=loc.photo_attachment_id,
        light_children=loc.light_children,
        grid_row=loc.grid_row,
        grid_col=loc.grid_col,
        path=await location_path(db, loc.id),
        created_at=loc.created_at,
        updated_at=loc.updated_at,
    )


async def tree(db: AsyncSession) -> list[LocationNode]:
    locs = await _all(db)
    types = await _type_names(db)
    nodes = {
        lid: LocationNode(
            id=loc.id,
            name=loc.name,
            code=loc.code,
            type_name=types.get(loc.location_type_id) if loc.location_type_id else None,
        )
        for lid, loc in locs.items()
    }
    roots: list[LocationNode] = []
    for lid, loc in locs.items():
        parent = nodes.get(loc.parent_id) if loc.parent_id else None
        (parent.children if parent else roots).append(nodes[lid])

    def sort(ns: list[LocationNode]) -> list[LocationNode]:
        ns.sort(key=lambda n: (n.name.lower(), n.id))
        for n in ns:
            sort(n.children)
        return ns

    return sort(roots)


async def _code_taken(db: AsyncSession, code: str, exclude_location: int | None = None) -> bool:
    from pick2light.models import Barcode

    bc = await db.scalar(select(Barcode).where(Barcode.code == code))
    if bc is not None and not (bc.target_type == "location" and bc.target_id == exclude_location):
        return True
    other = await db.scalar(select(Location.id).where(Location.code == code))
    return other is not None and other != exclude_location


async def _new_code(db: AsyncSession) -> str:
    while True:
        n = await db.scalar(text("SELECT nextval('location_code_seq')"))
        code = f"LOC-{int(n):04d}"
        if not await _code_taken(db, code):
            return code


async def _clean_code(db: AsyncSession, code: str, exclude_location: int | None = None) -> str:
    clean = sanitize_code(code)
    if not clean:
        raise ValidationFailed({"code": "Use letters, digits, '.', '_' or '-'"})
    if await _code_taken(db, clean, exclude_location):
        raise Conflict(f"Code '{clean}' is already in use")
    return clean


async def _check_type(db: AsyncSession, type_id: int | None) -> None:
    if type_id is not None and await db.get(LocationType, type_id) is None:
        raise ValidationFailed({"location_type_id": "Unknown location type"})


async def create_location(db: AsyncSession, data: LocationIn) -> Location:
    if data.parent_id is not None:
        await get_location(db, data.parent_id)
    await _check_type(db, data.location_type_id)
    code = await _clean_code(db, data.code) if data.code else await _new_code(db)
    loc = Location(
        name=data.name.strip(),
        parent_id=data.parent_id,
        location_type_id=data.location_type_id,
        code=code,
        notes=data.notes,
        light_children=data.light_children,
        grid_row=data.grid_row,
        grid_col=data.grid_col,
    )
    db.add(loc)
    await db.flush()
    await register_barcode(db, code, "location", loc.id, "location_code")
    return loc


async def update_location(db: AsyncSession, location_id: int, data: LocationPatch) -> Location:
    loc = await get_location(db, location_id)
    sent = data.model_fields_set
    if "code" in sent and data.code and data.code != loc.code:
        code = await _clean_code(db, data.code, exclude_location=loc.id)
        await remove_barcodes_for(db, "location", loc.id, kind="location_code")
        loc.code = code
        await db.flush()
        await register_barcode(db, code, "location", loc.id, "location_code")
    if "location_type_id" in sent:
        await _check_type(db, data.location_type_id)
        loc.location_type_id = data.location_type_id
    for attr in ("notes", "grid_row", "grid_col", "photo_attachment_id"):
        if attr in sent:
            setattr(loc, attr, getattr(data, attr))
    if data.name is not None:
        loc.name = data.name.strip()
    if data.light_children is not None:
        loc.light_children = data.light_children
    await db.flush()
    return loc


async def move_location(db: AsyncSession, location_id: int, new_parent_id: int | None) -> Location:
    loc = await get_location(db, location_id)
    if new_parent_id is not None:
        await get_location(db, new_parent_id)
        if new_parent_id in _descendants(await _all(db), loc.id):
            raise Conflict("A location can't be moved inside itself")
    loc.parent_id = new_parent_id
    await db.flush()
    return loc


async def _contents_check(db: AsyncSession, location_id: int) -> None:
    """Refuse deleting a location that still holds stock or units."""


async def delete_location(db: AsyncSession, location_id: int) -> None:
    loc = await get_location(db, location_id)
    children = await db.scalar(
        select(func.count())
        .select_from(Location)
        .where(Location.parent_id == loc.id, Location.deleted_at.is_(None))
    )
    if children:
        raise Conflict(f"'{loc.name}' contains other locations; move or delete them first")
    await _contents_check(db, loc.id)
    loc.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "location", loc.id)
    await db.flush()
