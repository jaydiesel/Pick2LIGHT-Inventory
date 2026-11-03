from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pick2light.api.deps import DB
from pick2light.core import stock as svc
from pick2light.core.stock import LowStockRow, MovementOut, StockRow
from pick2light.core.units import UnitOut, get_unit_out

router = APIRouter(tags=["stock"])


class AddIn(BaseModel):
    item_id: int
    location_id: int
    quantity: float = Field(gt=0)
    note: str | None = None


class RemoveIn(AddIn):
    reason: Literal["check_out", "consume"] = "check_out"


class MoveIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    quantity: float = Field(gt=0)
    note: str | None = None


class AdjustIn(BaseModel):
    item_id: int
    location_id: int
    counted: float = Field(ge=0)
    note: str | None = None


class UnitLocationIn(BaseModel):
    location_id: int | None = None
    note: str | None = None


class UnitMoveIn(BaseModel):
    location_id: int
    note: str | None = None


class ConditionIn(BaseModel):
    condition: svc.Condition


async def _one(db, movement) -> MovementOut:
    rows = await svc.list_movements(db, item_id=movement.item_id, unit_id=movement.unit_id, limit=200)
    return next(r for r in rows if r.id == movement.id)


@router.get("/items/{item_id}/stock")
async def item_stock(item_id: int, db: DB) -> list[StockRow]:
    return await svc.item_stock(db, item_id)


@router.post("/stock/add")
async def add(data: AddIn, db: DB) -> MovementOut:
    return await _one(
        db, await svc.add_stock(db, data.item_id, data.location_id, data.quantity, note=data.note)
    )


@router.post("/stock/remove")
async def remove(data: RemoveIn, db: DB) -> MovementOut:
    m = await svc.remove_stock(
        db, data.item_id, data.location_id, data.quantity, reason=data.reason, note=data.note
    )
    return await _one(db, m)


@router.post("/stock/move")
async def move(data: MoveIn, db: DB) -> MovementOut:
    m = await svc.move_stock(
        db, data.item_id, data.from_location_id, data.to_location_id, data.quantity, note=data.note
    )
    return await _one(db, m)


@router.post("/stock/adjust")
async def adjust(data: AdjustIn, db: DB) -> MovementOut | None:
    m = await svc.adjust_stock(db, data.item_id, data.location_id, data.counted, note=data.note)
    return await _one(db, m) if m else None


@router.get("/stock/low")
async def low(db: DB) -> list[LowStockRow]:
    return await svc.low_stock(db)


@router.post("/units/{unit_id}/check-out")
async def unit_check_out(unit_id: int, db: DB, data: UnitLocationIn | None = None) -> UnitOut:
    await svc.check_out_unit(db, unit_id, note=data.note if data else None)
    return await get_unit_out(db, unit_id)


@router.post("/units/{unit_id}/check-in")
async def unit_check_in(unit_id: int, db: DB, data: UnitLocationIn | None = None) -> UnitOut:
    await svc.check_in_unit(db, unit_id, data.location_id if data else None, note=data.note if data else None)
    return await get_unit_out(db, unit_id)


@router.post("/units/{unit_id}/consume")
async def unit_consume(unit_id: int, db: DB, data: UnitLocationIn | None = None) -> UnitOut:
    await svc.consume_unit(db, unit_id, note=data.note if data else None)
    return await get_unit_out(db, unit_id)


@router.post("/units/{unit_id}/dispose")
async def unit_dispose(unit_id: int, db: DB, data: UnitLocationIn | None = None) -> UnitOut:
    await svc.dispose_unit(db, unit_id, note=data.note if data else None)
    return await get_unit_out(db, unit_id)


@router.post("/units/{unit_id}/move")
async def unit_move(unit_id: int, data: UnitMoveIn, db: DB) -> UnitOut:
    await svc.move_unit(db, unit_id, data.location_id, note=data.note)
    return await get_unit_out(db, unit_id)


@router.patch("/units/{unit_id}/condition")
async def unit_condition(unit_id: int, data: ConditionIn, db: DB) -> UnitOut:
    await svc.set_condition(db, unit_id, data.condition)
    return await get_unit_out(db, unit_id)


@router.get("/movements")
async def movements(
    db: DB,
    item_id: int | None = None,
    unit_id: int | None = None,
    limit: int = 50,
    before_id: int | None = None,
) -> list[MovementOut]:
    return await svc.list_movements(db, item_id=item_id, unit_id=unit_id, limit=limit, before_id=before_id)


@router.post("/movements/{movement_id}/undo")
async def undo(movement_id: int, db: DB) -> MovementOut:
    return await _one(db, await svc.undo_movement(db, movement_id))
