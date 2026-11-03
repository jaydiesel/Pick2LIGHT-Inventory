from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from pick2light.api.deps import DB
from pick2light.core import stock as svc
from pick2light.core import units as unit_svc
from pick2light.core.stock import LowStockRow, MovementOut, StockRow
from pick2light.core.units import UnitOut

router = APIRouter(tags=["stock"])

Source = Literal["ui", "scan", "import", "api", "stocktake"]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class StockOpIn(BaseModel):
    item_id: int
    location_id: int
    quantity: Quantity
    source: Source = "ui"
    note: str | None = None


class RemoveIn(StockOpIn):
    reason: Literal["check_out", "consume"] = "check_out"


class MoveIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    quantity: Quantity
    source: Source = "ui"
    note: str | None = None


class AdjustIn(BaseModel):
    item_id: int
    location_id: int
    counted: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
    source: Source = "ui"
    note: str | None = None


class UnitOpIn(BaseModel):
    source: Source = "ui"
    note: str | None = None


class CheckInIn(UnitOpIn):
    location_id: int | None = None


class MoveUnitIn(UnitOpIn):
    location_id: int


class ConditionIn(BaseModel):
    condition: unit_svc.Condition


class UndoIn(UnitOpIn):
    pass


class AdjustOut(BaseModel):
    """`movement` is null when the counted value already matched."""

    movement: MovementOut | None


@router.get("/items/{item_id}/stock")
async def item_stock(item_id: int, db: DB) -> list[StockRow]:
    return await svc.item_stock(db, item_id)


@router.post("/stock/add", status_code=201)
async def add_stock(data: StockOpIn, db: DB) -> MovementOut:
    m = await svc.add_stock(
        db, data.item_id, data.location_id, data.quantity, source=data.source, note=data.note
    )
    return svc.movement_out(m)


@router.post("/stock/remove", status_code=201)
async def remove_stock(data: RemoveIn, db: DB) -> MovementOut:
    m = await svc.remove_stock(
        db,
        data.item_id,
        data.location_id,
        data.quantity,
        reason=data.reason,
        source=data.source,
        note=data.note,
    )
    return svc.movement_out(m)


@router.post("/stock/move", status_code=201)
async def move_stock(data: MoveIn, db: DB) -> MovementOut:
    m = await svc.move_stock(
        db,
        data.item_id,
        data.from_location_id,
        data.to_location_id,
        data.quantity,
        source=data.source,
        note=data.note,
    )
    return svc.movement_out(m)


@router.post("/stock/adjust")
async def adjust_stock(data: AdjustIn, db: DB) -> AdjustOut:
    m = await svc.adjust_stock(
        db, data.item_id, data.location_id, data.counted, source=data.source, note=data.note
    )
    return AdjustOut(movement=svc.movement_out(m) if m else None)


@router.get("/stock/low")
async def low_stock(db: DB) -> list[LowStockRow]:
    return await svc.low_stock(db)


@router.post("/units/{unit_id}/check-out", status_code=201)
async def check_out_unit(unit_id: int, db: DB, data: UnitOpIn | None = None) -> MovementOut:
    data = data or UnitOpIn()
    return svc.movement_out(
        await svc.check_out_unit(db, unit_id, source=data.source, note=data.note)
    )


@router.post("/units/{unit_id}/check-in", status_code=201)
async def check_in_unit(unit_id: int, db: DB, data: CheckInIn | None = None) -> MovementOut:
    data = data or CheckInIn()
    m = await svc.check_in_unit(db, unit_id, data.location_id, source=data.source, note=data.note)
    return svc.movement_out(m)


@router.post("/units/{unit_id}/consume", status_code=201)
async def consume_unit(unit_id: int, db: DB, data: UnitOpIn | None = None) -> MovementOut:
    data = data or UnitOpIn()
    return svc.movement_out(await svc.consume_unit(db, unit_id, source=data.source, note=data.note))


@router.post("/units/{unit_id}/dispose", status_code=201)
async def dispose_unit(unit_id: int, db: DB, data: UnitOpIn | None = None) -> MovementOut:
    data = data or UnitOpIn()
    return svc.movement_out(await svc.dispose_unit(db, unit_id, source=data.source, note=data.note))


@router.post("/units/{unit_id}/move", status_code=201)
async def move_unit(unit_id: int, data: MoveUnitIn, db: DB) -> MovementOut:
    m = await svc.move_unit(db, unit_id, data.location_id, source=data.source, note=data.note)
    return svc.movement_out(m)


@router.patch("/units/{unit_id}/condition")
async def set_condition(unit_id: int, data: ConditionIn, db: DB) -> UnitOut:
    return await unit_svc.unit_out(db, await svc.set_condition(db, unit_id, data.condition))


@router.get("/movements")
async def list_movements(
    db: DB,
    item_id: int | None = None,
    unit_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: int | None = None,
) -> list[MovementOut]:
    return await svc.list_movements(
        db, item_id=item_id, unit_id=unit_id, limit=limit, before_id=before_id
    )


@router.post("/movements/{movement_id}/undo", status_code=201)
async def undo_movement(movement_id: int, db: DB, data: UndoIn | None = None) -> MovementOut:
    data = data or UndoIn()
    m = await svc.undo_movement(db, movement_id, source=data.source, note=data.note)
    return svc.movement_out(m)
