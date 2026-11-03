"""Every stock change goes through here and writes a stock_movement row (spec §4.3)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core.locations import LocationRef, get_location, location_path
from pick2light.errors import Conflict, InvalidOperation, NotFound
from pick2light.models import Item, Location, Stock, StockMovement, Unit

Source = Literal["ui", "scan", "import", "api", "stocktake"]
Condition = Literal["new", "tested_good", "untested", "faulty", "for_parts"]


class StockRow(BaseModel):
    location_id: int
    location_path: list[LocationRef]
    quantity: float


class LowStockRow(BaseModel):
    item_id: int
    name: str
    sku: str
    on_hand: float
    min_stock: int


class MovementOut(BaseModel):
    id: int
    item_id: int | None
    item_name: str | None
    item_sku: str | None
    unit_id: int | None
    unit_code: str | None
    from_location: LocationRef | None
    to_location: LocationRef | None
    quantity_delta: float
    reason: str
    source: str
    note: str | None
    reverses_movement_id: int | None
    reversed: bool
    created_at: datetime


def fmt_qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


# ---------------------------------------------------------------- helpers


async def _item(db: AsyncSession, item_id: int) -> Item:
    item = await db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound(f"Item {item_id} not found")
    return item


async def _unit(db: AsyncSession, unit_id: int) -> Unit:
    unit = await db.scalar(
        select(Unit).where(Unit.id == unit_id).with_for_update().execution_options(populate_existing=True)
    )
    if unit is None or unit.deleted_at is not None:
        raise NotFound(f"Unit {unit_id} not found")
    return unit


async def _bulk_item(db: AsyncSession, item_id: int) -> Item:
    item = await _item(db, item_id)
    if await cats.effective_tracking_mode(db, item.category_id) != "bulk":
        raise InvalidOperation(f"'{item.name}' is tracked per unit; use the unit actions instead")
    return item


def _positive(qty: float) -> None:
    if qty is None or qty <= 0:
        raise InvalidOperation("Quantity must be greater than zero")


async def _locked_row(db: AsyncSession, item_id: int, location_id: int) -> Stock:
    await db.execute(
        pg_insert(Stock)
        .values(item_id=item_id, location_id=location_id, quantity=0)
        .on_conflict_do_nothing(index_elements=["item_id", "location_id"])
    )
    row = await db.scalar(
        select(Stock)
        .where(Stock.item_id == item_id, Stock.location_id == location_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _change(db: AsyncSession, item_id: int, location_id: int, delta: float) -> Stock:
    row = await _locked_row(db, item_id, location_id)
    new_qty = float(row.quantity) + delta
    if new_qty < -1e-9:
        loc = await db.get(Location, location_id)
        name = loc.name if loc else f"location {location_id}"
        raise InvalidOperation(f"Only {fmt_qty(float(row.quantity))} in {name}")
    row.quantity = max(new_qty, 0.0)
    await db.flush()
    return row


async def record_movement(
    db: AsyncSession,
    *,
    item_id: int | None,
    reason: str,
    quantity_delta: float,
    unit_id: int | None = None,
    from_location_id: int | None = None,
    to_location_id: int | None = None,
    source: str = "ui",
    note: str | None = None,
    reverses_movement_id: int | None = None,
) -> StockMovement:
    m = StockMovement(
        item_id=item_id,
        unit_id=unit_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity_delta=quantity_delta,
        reason=reason,
        source=source,
        note=note,
        reverses_movement_id=reverses_movement_id,
    )
    db.add(m)
    await db.flush()
    return m


# ---------------------------------------------------------------- bulk


async def add_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    qty: float,
    *,
    reason: str = "check_in",
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    _positive(qty)
    await _bulk_item(db, item_id)
    await get_location(db, location_id)
    await _change(db, item_id, location_id, qty)
    return await record_movement(
        db,
        item_id=item_id,
        reason=reason,
        quantity_delta=qty,
        to_location_id=location_id,
        source=source,
        note=note,
    )


async def remove_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    qty: float,
    *,
    reason: str = "check_out",
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    _positive(qty)
    if reason not in ("check_out", "consume"):
        raise InvalidOperation("Reason must be check_out or consume")
    await _bulk_item(db, item_id)
    await get_location(db, location_id)
    await _change(db, item_id, location_id, -qty)
    return await record_movement(
        db,
        item_id=item_id,
        reason=reason,
        quantity_delta=-qty,
        from_location_id=location_id,
        source=source,
        note=note,
    )


async def move_stock(
    db: AsyncSession,
    item_id: int,
    from_id: int,
    to_id: int,
    qty: float,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    _positive(qty)
    if from_id == to_id:
        raise InvalidOperation("Choose a different location to move to")
    await _bulk_item(db, item_id)
    await get_location(db, from_id)
    await get_location(db, to_id)
    for loc_id, delta in sorted([(from_id, -qty), (to_id, qty)]):  # stable lock order
        await _change(db, item_id, loc_id, delta)
    return await record_movement(
        db,
        item_id=item_id,
        reason="move",
        quantity_delta=qty,
        from_location_id=from_id,
        to_location_id=to_id,
        source=source,
        note=note,
    )


async def adjust_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    counted: float,
    *,
    source: str = "ui",
    note: str | None = None,
    reason: str = "adjust",
) -> StockMovement | None:
    if counted is None or counted < 0:
        raise InvalidOperation("Counted quantity can't be negative")
    await _bulk_item(db, item_id)
    await get_location(db, location_id)
    row = await _locked_row(db, item_id, location_id)
    delta = counted - float(row.quantity)
    if abs(delta) < 1e-9:
        return None
    row.quantity = counted
    await db.flush()
    return await record_movement(
        db,
        item_id=item_id,
        reason=reason,
        quantity_delta=delta,
        to_location_id=location_id if delta > 0 else None,
        from_location_id=location_id if delta < 0 else None,
        source=source,
        note=note,
    )


# ---------------------------------------------------------------- units


def _require(unit: Unit, allowed: tuple[str, ...], action: str) -> None:
    if unit.status not in allowed:
        raise InvalidOperation(
            f"Unit {unit.unit_code} is {unit.status.replace('_', ' ')}; it can't be {action}"
        )


async def check_out_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    unit = await _unit(db, unit_id)
    _require(unit, ("in_stock",), "checked out")
    unit.status = "checked_out"
    await db.flush()
    return await record_movement(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        reason="check_out",
        quantity_delta=-1,
        from_location_id=unit.location_id,
        source=source,
        note=note,
    )


async def check_in_unit(
    db: AsyncSession,
    unit_id: int,
    location_id: int | None = None,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    unit = await _unit(db, unit_id)
    _require(unit, ("checked_out",), "checked in")
    if location_id is not None:
        await get_location(db, location_id)
        unit.location_id = location_id
    unit.status = "in_stock"
    await db.flush()
    return await record_movement(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        reason="check_in",
        quantity_delta=1,
        to_location_id=unit.location_id,
        source=source,
        note=note,
    )


async def _retire(
    db: AsyncSession, unit_id: int, status: str, reason: str, source: str, note: str | None
) -> StockMovement:
    unit = await _unit(db, unit_id)
    _require(unit, ("in_stock", "checked_out"), "used up" if status == "consumed" else "disposed of")
    from_loc = unit.location_id
    unit.status = status
    unit.location_id = None
    await db.flush()
    return await record_movement(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        reason=reason,
        quantity_delta=-1,
        from_location_id=from_loc,
        source=source,
        note=note,
    )


async def consume_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    return await _retire(db, unit_id, "consumed", "consume", source, note)


async def dispose_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    return await _retire(db, unit_id, "disposed", "consume", source, note or "disposed")


async def move_unit(
    db: AsyncSession, unit_id: int, location_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    unit = await _unit(db, unit_id)
    _require(unit, ("in_stock", "checked_out"), "moved")
    await get_location(db, location_id)
    if unit.location_id == location_id:
        raise InvalidOperation("The unit is already there")
    from_loc = unit.location_id
    unit.location_id = location_id
    await db.flush()
    return await record_movement(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        reason="move",
        quantity_delta=0,
        from_location_id=from_loc,
        to_location_id=location_id,
        source=source,
        note=note,
    )


async def set_condition(db: AsyncSession, unit_id: int, condition: str) -> Unit:
    unit = await _unit(db, unit_id)
    unit.condition = condition
    await db.flush()
    return unit


# ---------------------------------------------------------------- undo


async def undo_movement(db: AsyncSession, movement_id: int, *, source: str = "ui") -> StockMovement:
    m = await db.scalar(select(StockMovement).where(StockMovement.id == movement_id).with_for_update())
    if m is None:
        raise NotFound(f"Movement {movement_id} not found")
    if m.reason == "undo":
        raise Conflict("An undo can't be undone; make a new change instead")
    already = await db.scalar(select(StockMovement.id).where(StockMovement.reverses_movement_id == m.id))
    if already is not None:
        raise Conflict("This change has already been undone")

    async def emit(**kw: Any) -> StockMovement:
        return await record_movement(
            db, item_id=m.item_id, reason="undo", source=source, reverses_movement_id=m.id, **kw
        )

    if m.unit_id is None:
        if m.item_id is None:
            raise InvalidOperation("The item for this change no longer exists")
        if m.from_location_id and m.to_location_id:
            for move_loc, move_delta in sorted(
                [(m.to_location_id, -m.quantity_delta), (m.from_location_id, m.quantity_delta)]
            ):
                await _change(db, m.item_id, move_loc, move_delta)
            return await emit(
                quantity_delta=m.quantity_delta,
                from_location_id=m.to_location_id,
                to_location_id=m.from_location_id,
            )
        loc_id: int | None = m.to_location_id or m.from_location_id
        if loc_id is None:
            raise InvalidOperation("This change can't be undone")
        await _change(db, m.item_id, loc_id, -m.quantity_delta)
        return await emit(
            quantity_delta=-m.quantity_delta,
            to_location_id=loc_id if -m.quantity_delta > 0 else None,
            from_location_id=loc_id if -m.quantity_delta < 0 else None,
        )

    unit = await _unit(db, m.unit_id)
    delta: float
    frm: int | None
    to: int | None
    if m.reason == "check_out":
        _require(unit, ("checked_out",), "returned")
        unit.status = "in_stock"
        delta, frm, to = 1.0, None, unit.location_id
    elif m.reason == "check_in":
        _require(unit, ("in_stock",), "checked out again")
        unit.status = "checked_out"
        delta, frm, to = -1.0, unit.location_id, None
    elif m.reason == "consume":
        _require(unit, ("consumed", "disposed"), "restored")
        unit.status = "in_stock"
        unit.location_id = m.from_location_id
        delta, frm, to = 1.0, None, m.from_location_id
    elif m.reason == "move":
        _require(unit, ("in_stock", "checked_out"), "moved back")
        unit.location_id = m.from_location_id
        delta, frm, to = 0.0, m.to_location_id, m.from_location_id
    else:
        raise Conflict("Creating a unit can't be undone; delete the unit instead")
    await db.flush()
    return await emit(unit_id=unit.id, quantity_delta=delta, from_location_id=frm, to_location_id=to)


# ---------------------------------------------------------------- queries


async def on_hand(db: AsyncSession, item_id: int) -> float:
    item = await _item(db, item_id)
    if await cats.effective_tracking_mode(db, item.category_id) == "unit":
        count = await db.scalar(
            select(func.count())
            .select_from(Unit)
            .where(Unit.item_id == item_id, Unit.status == "in_stock", Unit.deleted_at.is_(None))
        )
        return float(count or 0)
    total = await db.scalar(
        select(func.coalesce(func.sum(Stock.quantity), 0)).where(Stock.item_id == item_id)
    )
    return float(total or 0)


async def item_stock(db: AsyncSession, item_id: int) -> list[StockRow]:
    await _item(db, item_id)
    rows = await db.scalars(select(Stock).where(Stock.item_id == item_id, Stock.quantity > 0))
    out = [
        StockRow(
            location_id=r.location_id,
            location_path=await location_path(db, r.location_id),
            quantity=float(r.quantity),
        )
        for r in rows
    ]
    return sorted(out, key=lambda r: [p.name.lower() for p in r.location_path])


def on_hand_expr() -> Any:
    """SQL expression for an item's on-hand quantity (bulk stock sum + in-stock units)."""
    stock_sum = (
        select(func.coalesce(func.sum(Stock.quantity), 0)).where(Stock.item_id == Item.id).scalar_subquery()
    )
    unit_count = (
        select(func.count())
        .select_from(Unit)
        .where(Unit.item_id == Item.id, Unit.status == "in_stock", Unit.deleted_at.is_(None))
        .scalar_subquery()
    )
    return cast(stock_sum, Numeric) + unit_count


async def low_stock(db: AsyncSession) -> list[LowStockRow]:
    qty = on_hand_expr()
    rows = await db.execute(
        select(Item.id, Item.name, Item.sku, qty, Item.min_stock)
        .where(Item.min_stock.is_not(None), Item.deleted_at.is_(None), qty < Item.min_stock)
        .order_by(func.lower(Item.name), Item.id)
    )
    return [
        LowStockRow(item_id=i, name=n, sku=sku, on_hand=float(q or 0), min_stock=m)
        for i, n, sku, q, m in rows
    ]


async def _ref(
    db: AsyncSession, location_id: int | None, cache: dict[int, LocationRef | None]
) -> LocationRef | None:
    if location_id is None:
        return None
    if location_id not in cache:
        loc = await db.get(Location, location_id)
        cache[location_id] = LocationRef(id=loc.id, name=loc.name, code=loc.code) if loc else None
    return cache[location_id]


async def list_movements(
    db: AsyncSession,
    *,
    item_id: int | None = None,
    unit_id: int | None = None,
    limit: int = 50,
    before_id: int | None = None,
) -> list[MovementOut]:
    q = select(StockMovement).order_by(StockMovement.id.desc()).limit(min(max(limit, 1), 200))
    if item_id is not None:
        q = q.where(StockMovement.item_id == item_id)
    if unit_id is not None:
        q = q.where(StockMovement.unit_id == unit_id)
    if before_id is not None:
        q = q.where(StockMovement.id < before_id)
    rows = list(await db.scalars(q))
    ids = [r.id for r in rows]
    reversed_ids = (
        set(
            await db.scalars(
                select(StockMovement.reverses_movement_id).where(StockMovement.reverses_movement_id.in_(ids))
            )
        )
        if ids
        else set()
    )
    cache: dict[int, LocationRef | None] = {}
    out = []
    for r in rows:
        item = await db.get(Item, r.item_id) if r.item_id else None
        unit = await db.get(Unit, r.unit_id) if r.unit_id else None
        out.append(
            MovementOut(
                id=r.id,
                item_id=r.item_id,
                item_name=item.name if item else None,
                item_sku=item.sku if item else None,
                unit_id=r.unit_id,
                unit_code=unit.unit_code if unit else None,
                from_location=await _ref(db, r.from_location_id, cache),
                to_location=await _ref(db, r.to_location_id, cache),
                quantity_delta=float(r.quantity_delta),
                reason=r.reason,
                source=r.source,
                note=r.note,
                reverses_movement_id=r.reverses_movement_id,
                reversed=r.id in reversed_ids,
                created_at=r.created_at,
            )
        )
    return out


async def location_has_contents(db: AsyncSession, location_id: int) -> bool:
    qty = await db.scalar(
        select(func.coalesce(func.sum(Stock.quantity), 0)).where(Stock.location_id == location_id)
    )
    if qty and float(qty) > 0:
        return True
    units = await db.scalar(
        select(func.count())
        .select_from(Unit)
        .where(
            Unit.location_id == location_id,
            Unit.deleted_at.is_(None),
            Unit.status.in_(["in_stock", "checked_out"]),
        )
    )
    return bool(units)
