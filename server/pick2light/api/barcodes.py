from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.api.deps import DB
from pick2light.core.barcodes import AUTOMATIC_KINDS, lookup_barcode, register_barcode
from pick2light.core.items import get_item
from pick2light.core.locations import get_location
from pick2light.core.units import get_unit
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Barcode

router = APIRouter(prefix="/barcodes", tags=["barcodes"])

# Each entry raises NotFound for a target that does not exist.
TARGET_CHECKS: dict[str, Callable[[AsyncSession, int], Awaitable[object]]] = {
    "item": get_item,
    "unit": get_unit,
    "location": get_location,
}


class BarcodeIn(BaseModel):
    code: str
    target_type: Literal["item", "unit", "location"]
    target_id: int
    kind: Literal["manufacturer", "supplier", "custom"]


class BarcodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    target_type: str
    target_id: int
    kind: str


@router.get("/{code:path}")
async def lookup(code: str, db: DB) -> BarcodeOut:
    barcode = await lookup_barcode(db, code)
    if barcode is None:
        raise NotFound(f"No barcode {code!r}")
    return BarcodeOut.model_validate(barcode)


@router.post("", status_code=201)
async def create_barcode(data: BarcodeIn, db: DB) -> BarcodeOut:
    check = TARGET_CHECKS.get(data.target_type)
    if check is None:
        raise ValidationFailed({"target_type": f"{data.target_type} barcodes are not supported"})
    await check(db, data.target_id)
    barcode = await register_barcode(db, data.code, data.target_type, data.target_id, data.kind)
    return BarcodeOut.model_validate(barcode)


@router.delete("/{barcode_id}", status_code=204)
async def delete_barcode(barcode_id: int, db: DB) -> Response:
    barcode = await db.get(Barcode, barcode_id)
    if barcode is None:
        raise NotFound(f"Barcode {barcode_id} not found")
    if barcode.kind in AUTOMATIC_KINDS:
        raise InvalidOperation("Automatic codes change with their owner and cannot be deleted")
    await db.delete(barcode)
    await db.flush()
    return Response(status_code=204)
