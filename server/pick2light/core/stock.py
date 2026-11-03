"""Stock operations: every quantity or unit status change goes through here.

Each operation changes `stock` / `unit` and appends a `stock_movement` row in the same
transaction. Services flush but never commit; the request-scoped session commits.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from pick2light.core.categories import effective_tracking_mode
from pick2light.core.items import get_item
from pick2light.core.items import on_hand as _item_on_hand
from pick2light.core.locations import LocationRef, get_location, location_path
from pick2light.errors import Conflict, InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Item, Location, Stock, StockMovement, Unit
from pick2light.models.inventory import UNIT_CONDITIONS

Number = Decimal | int | float


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
    item_id: int
    unit_id: int | None
    from_location_id: int | None
    to_location_id: int | None
    quantity_delta: float
    reason: str
    source: str
    reverses_movement_id: int | None
    note: str | None
    reversed: bool
    created_at: datetime


# --- helpers ----------------------------------------------------------------------------------


def _fmt(quantity: Decimal) -> str:
    return format(quantity.normalize(), "f")


def _positive(quantity: Number, *, allow_zero: bool = False) -> Decimal:
    value = Decimal(str(quantity))
    if value < 0 or (value == 0 and not allow_zero):
        raise ValidationFailed({"quantity": "must be greater than 0"})
    return value


async def _bulk_item(db: AsyncSession, item_id: int) -> Item:
    item = await get_item(db, item_id)
    if await effective_tracking_mode(db, item.category_id) != "bulk":
        raise InvalidOperation("This item is tracked as individual units; use unit operations")
    return item


async def _location(db: AsyncSession, location_id: int) -> Location:
    try:
        return await get_location(db, location_id)
    except NotFound:
        raise ValidationFailed({"location_id": "Location not found"}) from None


async def _lock_stock(db: AsyncSession, item_id: int, location_id: int) -> Stock:
    """The stock row, created if missing, locked until the transaction ends."""
    await db.execute(
        pg_insert(Stock)
        .values(item_id=item_id, location_id=location_id, quantity=0)
        .on_conflict_do_nothing(index_elements=["item_id", "location_id"])
    )
    return (
        await db.execute(
            select(Stock)
            .where(Stock.item_id == item_id, Stock.location_id == location_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _lock_unit(db: AsyncSession, unit_id: int) -> Unit:
    unit = (
        await db.execute(
            select(Unit)
            .where(Unit.id == unit_id, Unit.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if unit is None:
        raise NotFound(f"Unit {unit_id} not found")
    return unit


async def _record(
    db: AsyncSession,
    *,
    item_id: int,
    delta: Number,
    reason: str,
    source: str,
    note: str | None,
    unit_id: int | None = None,
    from_id: int | None = None,
    to_id: int | None = None,
    reverses: int | None = None,
) -> StockMovement:
    movement = StockMovement(
        item_id=item_id,
        unit_id=unit_id,
        from_location_id=from_id,
        to_location_id=to_id,
        quantity_delta=Decimal(str(delta)),
        reason=reason,
        source=source,
        reverses_movement_id=reverses,
        note=note,
    )
    db.add(movement)
    await db.flush()
    await db.refresh(movement)
    return movement


# --- bulk operations (internal: also used by undo) ---------------------------------------------


async def _add(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    quantity: Number,
    *,
    reason: str,
    source: str,
    note: str | None,
    reverses: int | None = None,
) -> StockMovement:
    qty = _positive(quantity)
    await _bulk_item(db, item_id)
    await _location(db, location_id)
    row = await _lock_stock(db, item_id, location_id)
    row.quantity += qty
    await db.flush()
    return await _record(
        db,
        item_id=item_id,
        delta=qty,
        reason=reason,
        source=source,
        note=note,
        to_id=location_id,
        reverses=reverses,
    )


async def _remove(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    quantity: Number,
    *,
    reason: str,
    source: str,
    note: str | None,
    reverses: int | None = None,
) -> StockMovement:
    qty = _positive(quantity)
    await _bulk_item(db, item_id)
    location = await _location(db, location_id)
    row = await _lock_stock(db, item_id, location_id)
    if row.quantity < qty:
        raise InvalidOperation(f"Only {_fmt(row.quantity)} in {location.name}")
    row.quantity -= qty
    await db.flush()
    return await _record(
        db,
        item_id=item_id,
        delta=-qty,
        reason=reason,
        source=source,
        note=note,
        from_id=location_id,
        reverses=reverses,
    )


async def _move(
    db: AsyncSession,
    item_id: int,
    from_id: int,
    to_id: int,
    quantity: Number,
    *,
    reason: str,
    source: str,
    note: str | None,
    reverses: int | None = None,
) -> StockMovement:
    qty = _positive(quantity)
    if from_id == to_id:
        raise InvalidOperation("Source and destination are the same location")
    await _bulk_item(db, item_id)
    source_location = await _location(db, from_id)
    await _location(db, to_id)
    rows: dict[int, Stock] = {}
    for location_id in sorted((from_id, to_id)):  # fixed lock order: no deadlock between movers
        rows[location_id] = await _lock_stock(db, item_id, location_id)
    if rows[from_id].quantity < qty:
        raise InvalidOperation(f"Only {_fmt(rows[from_id].quantity)} in {source_location.name}")
    rows[from_id].quantity -= qty
    rows[to_id].quantity += qty
    await db.flush()
    return await _record(
        db,
        item_id=item_id,
        delta=qty,
        reason=reason,
        source=source,
        note=note,
        from_id=from_id,
        to_id=to_id,
        reverses=reverses,
    )


# --- bulk operations (public) ------------------------------------------------------------------


async def add_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    qty: Number,
    *,
    reason: Literal["check_in", "import"] = "check_in",
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    if reason not in ("check_in", "import"):
        raise InvalidOperation(f"Cannot add stock with reason {reason!r}")
    return await _add(db, item_id, location_id, qty, reason=reason, source=source, note=note)


async def remove_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    qty: Number,
    *,
    reason: Literal["check_out", "consume"] = "check_out",
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    if reason not in ("check_out", "consume"):
        raise InvalidOperation(f"Cannot remove stock with reason {reason!r}")
    return await _remove(db, item_id, location_id, qty, reason=reason, source=source, note=note)


async def move_stock(
    db: AsyncSession,
    item_id: int,
    from_id: int,
    to_id: int,
    qty: Number,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    return await _move(db, item_id, from_id, to_id, qty, reason="move", source=source, note=note)


async def adjust_stock(
    db: AsyncSession,
    item_id: int,
    location_id: int,
    counted: Number,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement | None:
    """Set the quantity to a counted value; the movement records the difference."""
    target = _positive(counted, allow_zero=True)
    await _bulk_item(db, item_id)
    await _location(db, location_id)
    row = await _lock_stock(db, item_id, location_id)
    delta = target - row.quantity
    if delta == 0:
        return None
    row.quantity = target
    await db.flush()
    return await _record(
        db,
        item_id=item_id,
        delta=delta,
        reason="adjust",
        source=source,
        note=note,
        to_id=location_id if delta > 0 else None,
        from_id=location_id if delta < 0 else None,
    )


# --- unit operations ---------------------------------------------------------------------------


def _not_allowed(unit: Unit, action: str) -> InvalidOperation:
    return InvalidOperation(f"Cannot {action} unit {unit.unit_code}: it is {unit.status}")


async def check_out_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    unit = await _lock_unit(db, unit_id)
    if unit.status != "in_stock":
        raise _not_allowed(unit, "check out")
    unit.status = "checked_out"  # the location stays as the unit's home
    await db.flush()
    return await _record(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        delta=-1,
        reason="check_out",
        source=source,
        note=note,
        from_id=unit.location_id,
    )


async def check_in_unit(
    db: AsyncSession,
    unit_id: int,
    location_id: int | None = None,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    unit = await _lock_unit(db, unit_id)
    if unit.status != "checked_out":
        raise _not_allowed(unit, "check in")
    destination = location_id if location_id is not None else unit.location_id
    if destination is None:
        raise InvalidOperation("Choose a location: this unit has no home location")
    await _location(db, destination)
    previous = unit.location_id
    unit.status = "in_stock"
    unit.location_id = destination
    await db.flush()
    return await _record(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        delta=1,
        reason="check_in",
        source=source,
        note=note,
        from_id=previous if previous != destination else None,
        to_id=destination,
    )


async def _retire_unit(
    db: AsyncSession, unit_id: int, *, status: str, source: str, note: str | None
) -> StockMovement:
    unit = await _lock_unit(db, unit_id)
    if unit.status not in ("in_stock", "checked_out"):
        raise _not_allowed(unit, "consume" if status == "consumed" else "dispose of")
    previous = unit.location_id
    unit.status = status
    unit.location_id = None
    await db.flush()
    return await _record(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        delta=-1,
        reason="consume",
        source=source,
        note=note,
        from_id=previous,
    )


async def consume_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    return await _retire_unit(db, unit_id, status="consumed", source=source, note=note)


async def dispose_unit(
    db: AsyncSession, unit_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    """Disposal has no reason of its own: it is recorded as `consume` with note "disposed"."""
    return await _retire_unit(
        db, unit_id, status="disposed", source=source, note=note or "disposed"
    )


async def move_unit(
    db: AsyncSession,
    unit_id: int,
    location_id: int,
    *,
    source: str = "ui",
    note: str | None = None,
) -> StockMovement:
    unit = await _lock_unit(db, unit_id)
    if unit.status != "in_stock":
        raise _not_allowed(unit, "move")
    await _location(db, location_id)
    if unit.location_id == location_id:
        raise InvalidOperation("The unit is already in that location")
    previous = unit.location_id
    unit.location_id = location_id
    await db.flush()
    return await _record(
        db,
        item_id=unit.item_id,
        unit_id=unit.id,
        delta=0,
        reason="move",
        source=source,
        note=note,
        from_id=previous,
        to_id=location_id,
    )


async def set_condition(db: AsyncSession, unit_id: int, condition: str) -> Unit:
    """Condition is a plain attribute: no movement."""
    if condition not in UNIT_CONDITIONS:
        raise ValidationFailed({"condition": f"must be one of {', '.join(UNIT_CONDITIONS)}"})
    unit = await _lock_unit(db, unit_id)
    unit.condition = condition
    await db.flush()
    await db.refresh(unit)
    return unit


# --- undo --------------------------------------------------------------------------------------


async def _live_location(db: AsyncSession, location_id: int) -> int:
    try:
        return (await get_location(db, location_id)).id
    except NotFound:
        raise InvalidOperation("The original location no longer exists") from None


async def _undo_unit(
    db: AsyncSession, m: StockMovement, *, source: str, note: str | None
) -> StockMovement:
    assert m.unit_id is not None
    if m.reason in ("create", "import"):
        raise Conflict("Creating a unit cannot be undone; delete the unit instead")
    unit = await _lock_unit(db, m.unit_id)

    async def record(
        delta: int, from_id: int | None = None, to_id: int | None = None
    ) -> StockMovement:
        return await _record(
            db,
            item_id=unit.item_id,
            unit_id=unit.id,
            delta=delta,
            reason="undo",
            source=source,
            note=note,
            from_id=from_id,
            to_id=to_id,
            reverses=m.id,
        )

    if m.reason == "check_out":
        if unit.status != "checked_out":
            raise _not_allowed(unit, "undo the check-out of")
        unit.status = "in_stock"
        await db.flush()
        return await record(1, to_id=unit.location_id)
    if m.reason == "check_in":
        if unit.status != "in_stock":
            raise _not_allowed(unit, "undo the check-in of")
        current = unit.location_id
        if m.from_location_id is not None:
            unit.location_id = await _live_location(db, m.from_location_id)
        unit.status = "checked_out"
        await db.flush()
        return await record(-1, from_id=current, to_id=unit.location_id)
    if m.reason == "consume":
        if unit.status not in ("consumed", "disposed"):
            raise _not_allowed(unit, "undo the consumption of")
        if m.from_location_id is not None:
            unit.location_id = await _live_location(db, m.from_location_id)
        unit.status = "in_stock"
        await db.flush()
        return await record(1, to_id=unit.location_id)
    if m.reason == "move":
        if unit.status != "in_stock":
            raise _not_allowed(unit, "undo the move of")
        assert m.from_location_id is not None or m.to_location_id is not None
        current = unit.location_id
        unit.location_id = (
            await _live_location(db, m.from_location_id) if m.from_location_id is not None else None
        )
        await db.flush()
        return await record(0, from_id=current, to_id=unit.location_id)
    raise Conflict(f"A {m.reason} movement cannot be undone")


async def undo_movement(
    db: AsyncSession, movement_id: int, *, source: str = "ui", note: str | None = None
) -> StockMovement:
    """Apply the inverse of a movement as a new `undo` movement; history is never rewritten."""
    m = (
        await db.execute(
            select(StockMovement)
            .where(StockMovement.id == movement_id)
            .with_for_update()  # serialises two undos of the same movement
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if m is None:
        raise NotFound(f"Movement {movement_id} not found")
    if m.reason == "undo":
        raise Conflict("An undo cannot itself be undone; repeat the original action instead")
    already = await db.scalar(
        select(StockMovement.id).where(StockMovement.reverses_movement_id == m.id).limit(1)
    )
    if already is not None:
        raise Conflict("This movement has already been undone")
    if m.unit_id is not None:
        return await _undo_unit(db, m, source=source, note=note)

    qty = m.quantity_delta
    if m.from_location_id is not None and m.to_location_id is not None:
        return await _move(
            db,
            m.item_id,
            m.to_location_id,
            m.from_location_id,
            qty,
            reason="undo",
            source=source,
            note=note,
            reverses=m.id,
        )
    if m.to_location_id is not None:
        return await _remove(
            db,
            m.item_id,
            m.to_location_id,
            qty,
            reason="undo",
            source=source,
            note=note,
            reverses=m.id,
        )
    if m.from_location_id is not None:
        return await _add(
            db,
            m.item_id,
            m.from_location_id,
            -qty,
            reason="undo",
            source=source,
            note=note,
            reverses=m.id,
        )
    raise Conflict("This movement has no location and cannot be undone")


# --- queries -----------------------------------------------------------------------------------


async def on_hand(db: AsyncSession, item_id: int) -> float:
    """Bulk: sum of stock across locations. Unit-tracked: count of `in_stock` units."""
    item = await get_item(db, item_id)
    return await _item_on_hand(db, item_id, await effective_tracking_mode(db, item.category_id))


async def low_stock(db: AsyncSession) -> list[LowStockRow]:
    """Items whose on-hand quantity is below `min_stock`, ordered by name.

    An item has either bulk stock or units (never both), so the two totals can be added.
    """
    bulk = (
        select(Stock.item_id, func.sum(Stock.quantity).label("qty"))
        .group_by(Stock.item_id)
        .subquery()
    )
    units = (
        select(Unit.item_id, func.count().label("qty"))
        .where(Unit.deleted_at.is_(None), Unit.status == "in_stock")
        .group_by(Unit.item_id)
        .subquery()
    )
    total = func.coalesce(bulk.c.qty, 0) + func.coalesce(units.c.qty, 0)
    rows = await db.execute(
        select(Item.id, Item.name, Item.sku, total, Item.min_stock)
        .outerjoin(bulk, bulk.c.item_id == Item.id)
        .outerjoin(units, units.c.item_id == Item.id)
        .where(Item.deleted_at.is_(None), Item.min_stock.is_not(None), total < Item.min_stock)
        .order_by(Item.name, Item.id)
    )
    return [
        LowStockRow(item_id=r[0], name=r[1], sku=r[2], on_hand=float(r[3]), min_stock=r[4])
        for r in rows
    ]


async def item_stock(db: AsyncSession, item_id: int) -> list[StockRow]:
    """Bulk quantities per location; rows at 0 are hidden."""
    await get_item(db, item_id)
    rows = await db.scalars(
        select(Stock).where(Stock.item_id == item_id, Stock.quantity > 0).order_by(Stock.id)
    )
    return [
        StockRow(
            location_id=row.location_id,
            location_path=await location_path(db, row.location_id),
            quantity=float(row.quantity),
        )
        for row in rows
    ]


async def list_movements(
    db: AsyncSession,
    *,
    item_id: int | None = None,
    unit_id: int | None = None,
    limit: int = 50,
    before_id: int | None = None,
) -> list[MovementOut]:
    """Newest first. `reversed` is true when a later undo movement points at the row."""
    undo = aliased(StockMovement)
    was_reversed = exists().where(undo.reverses_movement_id == StockMovement.id)
    query = select(StockMovement, was_reversed.label("reversed"))
    if item_id is not None:
        query = query.where(StockMovement.item_id == item_id)
    if unit_id is not None:
        query = query.where(StockMovement.unit_id == unit_id)
    if before_id is not None:
        query = query.where(StockMovement.id < before_id)
    rows = await db.execute(query.order_by(StockMovement.id.desc()).limit(limit))
    return [movement_out(m, reversed_=bool(flag)) for m, flag in rows]


def movement_out(m: StockMovement, *, reversed_: bool = False) -> MovementOut:
    return MovementOut(
        id=m.id,
        item_id=m.item_id,
        unit_id=m.unit_id,
        from_location_id=m.from_location_id,
        to_location_id=m.to_location_id,
        quantity_delta=float(m.quantity_delta),
        reason=m.reason,
        source=m.source,
        reverses_movement_id=m.reverses_movement_id,
        note=m.note,
        reversed=reversed_,
        created_at=m.created_at,
    )
