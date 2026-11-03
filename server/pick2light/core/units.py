"""Individually tracked units (spec §3.2 `unit`)."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core.barcodes import BarcodeOut, barcodes_for, register_barcode, remove_barcodes_for
from pick2light.core.fields import display_values, validate_values
from pick2light.core.items import ItemSummary, _check_location, get_item, summary
from pick2light.core.locations import LocationRef, location_path
from pick2light.core.sku import ensure_unique_code, generate_unit_code, sanitize_code
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Barcode, Unit

Condition = Literal["new", "tested_good", "untested", "faulty", "for_parts"]


class UnitIn(BaseModel):
    item_id: int
    unit_code: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=200)
    location_id: int | None = None
    condition: Condition = "untested"
    attrs: dict = {}


class UnitPatch(BaseModel):
    unit_code: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=200)
    attrs: dict | None = None


class UnitOut(BaseModel):
    id: int
    item_id: int
    item: ItemSummary
    unit_code: str
    serial_number: str | None
    location_id: int | None
    location_path: list[LocationRef]
    condition: str
    status: str
    attrs: dict
    attrs_display: dict[str, str]
    barcodes: list[BarcodeOut]
    created_at: datetime
    updated_at: datetime


async def get_unit(db: AsyncSession, unit_id: int) -> Unit:
    unit = await db.get(Unit, unit_id)
    if unit is None or unit.deleted_at is not None:
        raise NotFound(f"Unit {unit_id} not found")
    return unit


async def _code_taken(db: AsyncSession, code: str, exclude_unit: int | None = None) -> bool:
    bc = await db.scalar(select(Barcode).where(Barcode.code == code))
    if bc is not None and not (bc.target_type == "unit" and bc.target_id == exclude_unit):
        return True
    other = await db.scalar(select(Unit.id).where(Unit.unit_code == code))
    return other is not None and other != exclude_unit


async def _unique_code(db: AsyncSession, raw: str, exclude_unit: int | None = None) -> str:
    clean = sanitize_code(raw)
    if not clean:
        raise ValidationFailed({"unit_code": "Use letters, digits, '.', '_' or '-'"})

    async def exists(code: str) -> bool:
        return await _code_taken(db, code, exclude_unit)

    return await ensure_unique_code(clean, exists)


async def create_unit(db: AsyncSession, data: UnitIn, *, reason: str = "create", source: str = "ui") -> Unit:
    item = await get_item(db, data.item_id)
    if await cats.effective_tracking_mode(db, item.category_id) != "unit":
        raise InvalidOperation(f"'{item.name}' is tracked in bulk; add stock instead of units")
    await _check_location(db, data.location_id, field="location_id")
    specs = await cats.effective_fields(db, item.category_id, scope="unit")
    attrs = validate_values(specs, data.attrs, scope="unit")
    raw = (
        data.unit_code
        if data.unit_code and data.unit_code.strip()
        else await generate_unit_code(db, item.category_id, item.sku, attrs)
    )
    code = await _unique_code(db, raw)
    unit = Unit(
        item_id=item.id,
        unit_code=code,
        serial_number=(data.serial_number or "").strip() or None,
        location_id=data.location_id,
        condition=data.condition,
        status="in_stock",
        attrs=attrs,
    )
    db.add(unit)
    await db.flush()
    await register_barcode(db, code, "unit", unit.id, "unit_code")
    if unit.serial_number:
        await register_barcode(db, unit.serial_number, "unit", unit.id, "manufacturer")
    from pick2light.core.stock import record_movement

    await record_movement(
        db,
        item_id=item.id,
        unit_id=unit.id,
        reason=reason,
        quantity_delta=1,
        to_location_id=unit.location_id,
        source=source,
    )
    return unit


async def update_unit(db: AsyncSession, unit_id: int, patch: UnitPatch) -> Unit:
    unit = await get_unit(db, unit_id)
    item = await get_item(db, unit.item_id)
    sent = patch.model_fields_set
    if patch.attrs is not None:
        specs = await cats.effective_fields(db, item.category_id, scope="unit")
        unit.attrs = validate_values(specs, patch.attrs, existing=unit.attrs, scope="unit")
    if "unit_code" in sent and patch.unit_code and patch.unit_code != unit.unit_code:
        code = await _unique_code(db, patch.unit_code, exclude_unit=unit.id)
        await remove_barcodes_for(db, "unit", unit.id, kind="unit_code")
        unit.unit_code = code
        await db.flush()
        await register_barcode(db, code, "unit", unit.id, "unit_code")
    if "serial_number" in sent:
        new_serial = (patch.serial_number or "").strip() or None
        if new_serial != unit.serial_number:
            if unit.serial_number:
                old = await db.scalar(
                    select(Barcode).where(
                        Barcode.code == unit.serial_number,
                        Barcode.target_type == "unit",
                        Barcode.target_id == unit.id,
                    )
                )
                if old is not None:
                    await db.delete(old)
                    await db.flush()
            unit.serial_number = new_serial
            if new_serial:
                await register_barcode(db, new_serial, "unit", unit.id, "manufacturer")
    await db.flush()
    return unit


async def delete_unit(db: AsyncSession, unit_id: int) -> None:
    unit = await get_unit(db, unit_id)
    unit.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "unit", unit.id)
    await db.flush()


async def list_units(db: AsyncSession, item_id: int) -> list[Unit]:
    await get_item(db, item_id)
    return list(
        await db.scalars(
            select(Unit).where(Unit.item_id == item_id, Unit.deleted_at.is_(None)).order_by(Unit.unit_code)
        )
    )


async def get_unit_out(db: AsyncSession, unit_id: int) -> UnitOut:
    unit = await get_unit(db, unit_id)
    await db.refresh(unit)
    item = await get_item(db, unit.item_id)
    specs = await cats.effective_fields(db, item.category_id, scope="unit")
    return UnitOut(
        id=unit.id,
        item_id=item.id,
        item=summary(item),
        unit_code=unit.unit_code,
        serial_number=unit.serial_number,
        location_id=unit.location_id,
        location_path=await location_path(db, unit.location_id) if unit.location_id else [],
        condition=unit.condition,
        status=unit.status,
        attrs=unit.attrs or {},
        attrs_display=display_values(specs, unit.attrs or {}),
        barcodes=[BarcodeOut.model_validate(b) for b in await barcodes_for(db, "unit", unit.id)],
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )
