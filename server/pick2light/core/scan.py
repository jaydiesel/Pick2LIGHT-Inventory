"""Scan handling for the v0.1 modes: find, check-in, check-out, consume (§5.3)."""

from collections import deque
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import lookup_barcode
from pick2light.core.items import ItemOut, get_item, get_item_out
from pick2light.core.locations import LocationOut, LocationRef, get_location, location_out
from pick2light.core.stock import (
    StockRow,
    add_stock,
    check_in_unit,
    check_out_unit,
    consume_unit,
    item_stock,
    remove_stock,
)
from pick2light.core.units import UnitOut, get_unit, get_unit_out
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Barcode, Item, Location, Unit

Mode = Literal["find", "check_in", "check_out", "consume"]
SOURCE = "scan"
Action = Literal["found", "checked_in", "checked_out", "consumed", "needs_location", "error"]


class ScanRequest(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    mode: Mode = "find"
    quantity: float = Field(default=1, gt=0)
    location_id: int | None = None


class ScanResult(BaseModel):
    kind: Literal["item", "unit", "location", "unknown"]
    action: Action
    item: ItemOut | None = None
    unit: UnitOut | None = None
    location: LocationOut | None = None
    locations: list[StockRow | LocationRef] | None = None
    movement_id: int | None = None
    message: str


_DONE: dict[str, Action] = {
    "check_in": "checked_in",
    "check_out": "checked_out",
    "consume": "consumed",
}
_VERB = {"check_in": "Checked in", "check_out": "Checked out", "consume": "Consumed"}


def _fmt(quantity: float) -> str:
    return f"{quantity:g}"


async def _trashed_target(db: AsyncSession, code: str) -> str | None:
    """The target type of a barcode whose item, unit or location is in the trash."""
    rows = (await db.scalars(select(Barcode).where(func.lower(Barcode.code) == code.lower()))).all()
    exact = [b for b in rows if b.code == code]
    candidates = exact or (list(rows) if len(rows) == 1 else [])
    if not candidates:
        return None
    barcode = candidates[0]
    models: dict[str, type[Item] | type[Unit] | type[Location]] = {
        "item": Item,
        "unit": Unit,
        "location": Location,
    }
    model = models.get(barcode.target_type)
    target = await db.get(model, barcode.target_id) if model else None
    if target is not None and getattr(target, "deleted_at", None) is not None:
        return barcode.target_type
    return None


async def _stock_scan(db: AsyncSession, item: Item, req: ScanRequest) -> ScanResult:
    """Check in, check out or consume a bulk item."""
    item_id, item_name = item.id, item.name  # the mutation expires the row
    rows = await item_stock(db, item_id)
    location_id = req.location_id
    if req.mode == "check_in":
        if location_id is None:
            location_id = item.default_location_id
        if location_id is None:
            return await _result(
                db,
                "item",
                "needs_location",
                item_id=item_id,
                locations=[],
                message="Choose a location",
            )
    elif location_id is None:
        if not rows:
            raise InvalidOperation(f"No stock of {item_name} to take")
        if len(rows) > 1:
            return await _result(
                db,
                "item",
                "needs_location",
                item_id=item_id,
                locations=rows,
                message="Choose a location",
            )
        location_id = rows[0].location_id
    async with db.begin_nested():  # a failed scan must leave no partial write behind
        if req.mode == "check_in":
            movement = await add_stock(
                db, item_id, location_id, req.quantity, reason="check_in", source=SOURCE
            )
        else:
            movement = await remove_stock(
                db,
                item_id,
                location_id,
                req.quantity,
                reason="consume" if req.mode == "consume" else "check_out",
                source=SOURCE,
            )
    preposition = "to" if req.mode == "check_in" else "from"
    return await _result(
        db,
        "item",
        _DONE[req.mode],
        item_id=item_id,
        movement_id=movement.id,
        message=f"{_VERB[req.mode]} {_fmt(req.quantity)} x {item_name} {preposition} "
        f"{(await get_location(db, location_id)).name}",
    )


async def _unit_scan(db: AsyncSession, unit: Unit, req: ScanRequest) -> ScanResult:
    unit_id, unit_code = unit.id, unit.unit_code  # the mutation expires the row
    async with db.begin_nested():
        if req.mode == "check_out":
            movement = await check_out_unit(db, unit_id, source=SOURCE)
        elif req.mode == "check_in":
            movement = await check_in_unit(db, unit_id, req.location_id, source=SOURCE)
        else:
            movement = await consume_unit(db, unit_id, source=SOURCE)
    await db.refresh(unit)  # server-side updated_at
    return await _result(
        db,
        "unit",
        _DONE[req.mode],
        unit_id=unit_id,
        movement_id=movement.id,
        message=f"{_VERB[req.mode]} unit {unit_code}",
    )


async def _result(
    db: AsyncSession,
    kind: Literal["item", "unit", "location", "unknown"],
    action: Action,
    *,
    message: str,
    item_id: int | None = None,
    unit_id: int | None = None,
    location_id: int | None = None,
    locations: list[StockRow] | None = None,
    movement_id: int | None = None,
) -> ScanResult:
    """Build the response from fresh rows, so quantities and statuses reflect the scan."""
    unit_out = await get_unit_out(db, unit_id) if unit_id is not None else None
    if unit_out is not None and location_id is None:
        location_id = unit_out.location_id
    return ScanResult(
        kind=kind,
        action=action,
        item=await get_item_out(db, item_id) if item_id is not None else None,
        unit=unit_out,
        location=(
            await location_out(db, await get_location(db, location_id))
            if location_id is not None
            else None
        ),
        locations=list(locations) if locations is not None else None,
        movement_id=movement_id,
        message=message,
    )


async def handle_scan(db: AsyncSession, req: ScanRequest, recent_unknown: deque[str]) -> ScanResult:
    code = req.code.strip()
    barcode = await lookup_barcode(db, code)
    if barcode is None:
        trashed = await _trashed_target(db, code)
        if trashed is not None:
            kind: Literal["item", "unit", "location"] = trashed  # type: ignore[assignment]
            return ScanResult(kind=kind, action="error", message=f"This {trashed} is in the trash")
        if code in recent_unknown:
            recent_unknown.remove(code)
        recent_unknown.append(code)
        return ScanResult(kind="unknown", action="found", message=f"Unknown code {code}")

    try:
        if barcode.target_type == "location":
            location = await get_location(db, barcode.target_id)
            if req.mode != "find":
                return await _result(
                    db,
                    "location",
                    "error",
                    location_id=location.id,
                    message="Scan an item or unit in this mode",
                )
            return await _result(
                db,
                "location",
                "found",
                location_id=location.id,
                message=f"Location {location.name}",
            )

        if barcode.target_type == "unit":
            unit = await get_unit(db, barcode.target_id)
            if req.mode == "find":
                return await _result(
                    db, "unit", "found", unit_id=unit.id, message=f"Unit {unit.unit_code}"
                )
            return await _unit_scan(db, unit, req)

        item = await get_item(db, barcode.target_id)
        if req.mode == "find":
            return await _result(
                db,
                "item",
                "found",
                item_id=item.id,
                locations=await item_stock(db, item.id),
                message=item.name,
            )
        return await _stock_scan(db, item, req)
    except (InvalidOperation, ValidationFailed) as exc:
        return ScanResult(kind=_kind(barcode.target_type), action="error", message=exc.message)
    except NotFound as exc:
        return ScanResult(kind=_kind(barcode.target_type), action="error", message=exc.message)


def _kind(target_type: str) -> Literal["item", "unit", "location"]:
    if target_type == "unit":
        return "unit"
    return "location" if target_type == "location" else "item"
