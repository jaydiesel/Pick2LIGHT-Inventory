"""One registry for every scannable code (spec §3.2 `barcode`)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import Conflict, NotFound
from pick2light.models import Barcode

TargetType = Literal["item", "unit", "location"]
Kind = Literal["sku", "unit_code", "location_code", "manufacturer", "supplier", "custom"]
SYSTEM_KINDS = {"sku", "unit_code", "location_code"}


class BarcodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    target_type: TargetType
    target_id: int
    kind: Kind = "custom"


class BarcodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    target_type: str
    target_id: int
    kind: str


def normalize_code(code: str) -> str:
    return code.strip()


async def register_barcode(
    db: AsyncSession, code: str, target_type: str, target_id: int, kind: str
) -> Barcode:
    code = normalize_code(code)
    existing = await db.scalar(select(Barcode).where(Barcode.code == code))
    if existing is not None:
        if existing.target_type == target_type and existing.target_id == target_id:
            return existing
        raise Conflict(f"Code '{code}' is already used by another {existing.target_type}")
    bc = Barcode(code=code, target_type=target_type, target_id=target_id, kind=kind)
    db.add(bc)
    await db.flush()
    return bc


async def lookup_barcode(db: AsyncSession, code: str) -> Barcode | None:
    code = normalize_code(code)
    exact = await db.scalar(select(Barcode).where(Barcode.code == code))
    if exact is not None:
        return exact
    rows = list(await db.scalars(select(Barcode).where(func.lower(Barcode.code) == code.lower()).limit(2)))
    return rows[0] if len(rows) == 1 else None


async def code_exists(db: AsyncSession, code: str) -> bool:
    return (await db.scalar(select(Barcode.id).where(Barcode.code == normalize_code(code)))) is not None


async def remove_barcodes_for(
    db: AsyncSession, target_type: str, target_id: int, kind: str | None = None
) -> None:
    q = delete(Barcode).where(Barcode.target_type == target_type, Barcode.target_id == target_id)
    if kind is not None:
        q = q.where(Barcode.kind == kind)
    await db.execute(q)
    await db.flush()


async def barcodes_for(db: AsyncSession, target_type: str, target_id: int) -> list[Barcode]:
    return list(
        await db.scalars(
            select(Barcode)
            .where(Barcode.target_type == target_type, Barcode.target_id == target_id)
            .order_by(Barcode.id)
        )
    )


async def _target_exists(db: AsyncSession, target_type: str, target_id: int) -> bool:
    from pick2light.models import Item, Location, Unit

    models: dict[str, type] = {"location": Location, "item": Item, "unit": Unit}
    model = models.get(target_type)
    if model is None:
        return False
    row = await db.get(model, target_id)
    return row is not None and getattr(row, "deleted_at", None) is None


async def add_barcode(db: AsyncSession, data: BarcodeIn) -> Barcode:
    if data.kind in SYSTEM_KINDS:
        raise Conflict("SKU, unit and location codes are managed automatically")
    if not await _target_exists(db, data.target_type, data.target_id):
        raise NotFound(f"{data.target_type.capitalize()} {data.target_id} not found")
    return await register_barcode(db, data.code, data.target_type, data.target_id, data.kind)


async def delete_barcode(db: AsyncSession, barcode_id: int) -> None:
    bc = await db.get(Barcode, barcode_id)
    if bc is None:
        raise NotFound(f"Barcode {barcode_id} not found")
    if bc.kind in SYSTEM_KINDS:
        raise Conflict("This code is managed automatically; change the SKU or code instead")
    await db.delete(bc)
    await db.flush()
