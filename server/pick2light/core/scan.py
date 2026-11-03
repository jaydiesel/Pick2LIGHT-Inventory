"""Scan routing for v0.1 modes: find, check in, check out, consume (spec §5.2–5.3)."""

from collections import deque
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core import stock
from pick2light.core.barcodes import lookup_barcode
from pick2light.core.items import ItemOut, get_item, get_item_out
from pick2light.core.locations import LocationOut, LocationRef, get_location, location_path, to_out
from pick2light.core.stock import StockRow, fmt_qty
from pick2light.core.units import UnitOut, get_unit, get_unit_out
from pick2light.errors import InvalidOperation
from pick2light.models import Unit

Mode = Literal["find", "check_in", "check_out", "consume"]
Action = Literal["found", "checked_in", "checked_out", "consumed", "needs_location", "error"]


class ScanRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    mode: Mode = "find"
    quantity: float = Field(default=1, gt=0)
    location_id: int | None = None


class ScanResult(BaseModel):
    code: str
    kind: Literal["item", "unit", "location", "unknown"]
    action: Action
    item: ItemOut | None = None
    unit: UnitOut | None = None
    location: LocationOut | None = None
    locations: list[StockRow] | list[LocationRef] | None = None
    movement_id: int | None = None
    message: str


def remember_unknown(recent: deque[str], code: str) -> None:
    if code in recent:
        recent.remove(code)
    recent.append(code)


async def _unit_locations(db: AsyncSession, item_id: int) -> list[StockRow]:
    rows = await db.execute(
        select(Unit.location_id, func.count())
        .where(
            Unit.item_id == item_id,
            Unit.status == "in_stock",
            Unit.deleted_at.is_(None),
            Unit.location_id.is_not(None),
        )
        .group_by(Unit.location_id)
    )
    out = [
        StockRow(location_id=loc_id, location_path=await location_path(db, loc_id), quantity=float(n))
        for loc_id, n in rows
        if loc_id is not None
    ]
    return sorted(out, key=lambda r: [p.name.lower() for p in r.location_path])


async def _loc_name(db: AsyncSession, location_id: int) -> str:
    return (await get_location(db, location_id)).name


async def _item_scan(db: AsyncSession, req: ScanRequest, item_id: int, code: str) -> ScanResult:
    item = await get_item(db, item_id)
    unit_tracked = await cats.effective_tracking_mode(db, item.category_id) == "unit"
    rows = await _unit_locations(db, item.id) if unit_tracked else await stock.item_stock(db, item.id)

    def result(action: Action, message: str, **kw) -> ScanResult:
        return ScanResult(code=code, kind="item", action=action, message=message, **kw)

    if req.mode == "find":
        return result("found", item.name, item=await get_item_out(db, item.id), locations=rows)
    if unit_tracked:
        return result(
            "error",
            f"'{item.name}' is tracked per unit; scan the unit's own label",
            item=await get_item_out(db, item.id),
            locations=rows,
        )
    qty = req.quantity
    if req.mode == "check_in":
        loc_id = req.location_id or item.default_location_id
        if loc_id is None:
            return result(
                "needs_location", "Where should this go?", item=await get_item_out(db, item.id), locations=[]
            )
        m = await stock.add_stock(db, item.id, loc_id, qty, source="scan")
        return result(
            "checked_in",
            f"Checked in {fmt_qty(qty)} × {item.name} to {await _loc_name(db, loc_id)}",
            item=await get_item_out(db, item.id),
            movement_id=m.id,
        )
    # check_out / consume
    if req.location_id is not None:
        loc_id = req.location_id
    elif len(rows) == 1:
        loc_id = rows[0].location_id
    elif not rows:
        return result("error", f"No '{item.name}' in stock", item=await get_item_out(db, item.id))
    else:
        return result(
            "needs_location", "Which location?", item=await get_item_out(db, item.id), locations=rows
        )
    reason = "consume" if req.mode == "consume" else "check_out"
    m = await stock.remove_stock(db, item.id, loc_id, qty, reason=reason, source="scan")
    verb = "Used" if reason == "consume" else "Checked out"
    return result(
        "consumed" if reason == "consume" else "checked_out",
        f"{verb} {fmt_qty(qty)} × {item.name} from {await _loc_name(db, loc_id)}",
        item=await get_item_out(db, item.id),
        movement_id=m.id,
    )


async def _unit_scan(db: AsyncSession, req: ScanRequest, unit_id: int, code: str) -> ScanResult:
    unit = await get_unit(db, unit_id)
    if req.mode == "find":
        out = await get_unit_out(db, unit.id)
        return ScanResult(
            code=code,
            kind="unit",
            action="found",
            unit=out,
            locations=out.location_path[-1:],
            message=unit.unit_code,
        )
    if req.mode == "check_out":
        m = await stock.check_out_unit(db, unit.id, source="scan")
        action: Action = "checked_out"
        message = f"Checked out {unit.unit_code}"
    elif req.mode == "check_in":
        m = await stock.check_in_unit(db, unit.id, req.location_id, source="scan")
        action, message = "checked_in", f"Checked in {unit.unit_code}"
    else:
        m = await stock.consume_unit(db, unit.id, source="scan")
        action, message = "consumed", f"Marked {unit.unit_code} as used"
    return ScanResult(
        code=code,
        kind="unit",
        action=action,
        unit=await get_unit_out(db, unit.id),
        movement_id=m.id,
        message=message,
    )


async def handle_scan(db: AsyncSession, req: ScanRequest, recent_unknown: deque[str]) -> ScanResult:
    code = req.code.strip()
    bc = await lookup_barcode(db, code) if code else None
    if bc is None:
        if code:
            remember_unknown(recent_unknown, code)
        return ScanResult(code=code, kind="unknown", action="found", message=f"Unknown code {code}")
    if bc.target_type == "location":
        loc = await get_location(db, bc.target_id)
        if req.mode != "find":
            return ScanResult(
                code=code,
                kind="location",
                action="error",
                location=await to_out(db, loc),
                message="Scan an item or unit in this mode",
            )
        return ScanResult(
            code=code, kind="location", action="found", location=await to_out(db, loc), message=loc.name
        )
    try:
        async with db.begin_nested():
            if bc.target_type == "unit":
                return await _unit_scan(db, req, bc.target_id, code)
            return await _item_scan(db, req, bc.target_id, code)
    except InvalidOperation as exc:
        kind: Literal["item", "unit"] = "unit" if bc.target_type == "unit" else "item"
        return ScanResult(code=code, kind=kind, action="error", message=exc.message)
