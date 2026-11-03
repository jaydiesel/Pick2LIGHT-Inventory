"""Individually tracked units (one physical thing each, e.g. a labelled 18650 cell).

Services flush but never commit; the request-scoped session commits.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import code_exists, register_barcode, remove_barcodes_for
from pick2light.core.categories import effective_fields, effective_tracking_mode
from pick2light.core.fields import display_values, validate_values
from pick2light.core.items import get_item
from pick2light.core.locations import LocationRef, get_location, location_path
from pick2light.core.sku import ensure_unique_code, generate_unit_code, next_sequence, sanitize_code
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Barcode, Item, StockMovement, Unit

Condition = Literal["new", "tested_good", "untested", "faulty", "for_parts"]


class UnitIn(BaseModel):
    item_id: int
    unit_code: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    location_id: int | None = None
    condition: Condition = "untested"
    attrs: dict[str, Any] = {}


class UnitPatch(BaseModel):
    """Location and status change through stock operations, not here."""

    serial_number: str | None = Field(default=None, max_length=200)
    condition: Condition | None = None
    attrs: dict[str, Any] | None = None


class ItemSummary(BaseModel):
    id: int
    name: str
    sku: str


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
    attrs: dict[str, Any]
    attrs_display: dict[str, str]
    created_at: datetime
    updated_at: datetime


async def get_unit(db: AsyncSession, unit_id: int) -> Unit:
    unit = await db.get(Unit, unit_id)
    if unit is None or unit.deleted_at is not None:
        raise NotFound(f"Unit {unit_id} not found")
    return unit


async def unit_code_taken(db: AsyncSession, code: str) -> bool:
    """A code is taken by a barcode or by any unit row, soft-deleted ones included."""
    if await code_exists(db, code):
        return True
    return await db.scalar(select(Unit.id).where(Unit.unit_code == code).limit(1)) is not None


def _clean_serial(serial: str | None) -> str | None:
    serial = serial.strip() if serial else None
    return serial or None


async def create_unit(
    db: AsyncSession,
    data: UnitIn,
    *,
    reason: Literal["create", "import"] = "create",
    source: str = "ui",
) -> Unit:
    """Create a unit and its first movement (+1 into its location, if it has one)."""
    item = await get_item(db, data.item_id)
    if await effective_tracking_mode(db, item.category_id) != "unit":
        raise InvalidOperation("Units can only be created for items in unit-tracked categories")
    if data.location_id is not None:
        try:
            await get_location(db, data.location_id)
        except NotFound:
            raise ValidationFailed({"location_id": "Location not found"}) from None
    specs = await effective_fields(db, item.category_id, scope="unit")
    attrs = validate_values(specs, data.attrs, scope="unit")
    serial = _clean_serial(data.serial_number)

    if data.unit_code and data.unit_code.strip():
        code = sanitize_code(data.unit_code.strip()).upper()
        if not code:
            raise ValidationFailed({"unit_code": "must contain letters, digits, '.', '_' or '-'"})
    else:
        code = await generate_unit_code(db, item.category_id, item.sku, {**item.attrs, **attrs})
        if not code:
            seq = await next_sequence(db, item.category_id, "unit")
            code = f"UNIT-{seq:04d}"
    unit_code = await ensure_unique_code(code, lambda c: unit_code_taken(db, c))

    unit = Unit(
        item_id=item.id,
        unit_code=unit_code,
        serial_number=serial,
        location_id=data.location_id,
        condition=data.condition,
        attrs=attrs,
    )
    db.add(unit)
    await db.flush()
    await register_barcode(db, unit_code, "unit", unit.id, "unit_code")
    if serial:
        await register_barcode(db, serial, "unit", unit.id, "manufacturer")
    db.add(
        StockMovement(
            item_id=item.id,
            unit_id=unit.id,
            to_location_id=unit.location_id,
            quantity_delta=Decimal(1),
            reason=reason,
            source=source,
        )
    )
    await db.flush()
    return unit


async def update_unit(db: AsyncSession, unit_id: int, patch: UnitPatch) -> Unit:
    unit = await get_unit(db, unit_id)
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("condition", "") is None:
        raise ValidationFailed({"condition": "required"})
    if "attrs" in changes and changes["attrs"] is not None:
        item = await db.get(Item, unit.item_id)
        assert item is not None
        specs = await effective_fields(db, item.category_id, scope="unit")
        unit.attrs = validate_values(specs, changes["attrs"], existing=unit.attrs, scope="unit")
    if "condition" in changes:
        unit.condition = changes["condition"]
    if "serial_number" in changes:
        serial = _clean_serial(changes["serial_number"])
        if serial != unit.serial_number:
            if serial:  # fails first (Conflict) if another target already owns this code
                await register_barcode(db, serial, "unit", unit.id, "manufacturer")
            if unit.serial_number:
                await db.execute(
                    delete(Barcode).where(
                        Barcode.code == unit.serial_number,
                        Barcode.target_type == "unit",
                        Barcode.target_id == unit.id,
                        Barcode.kind == "manufacturer",
                    )
                )
            unit.serial_number = serial
    await db.flush()
    await db.refresh(unit)  # picks up the server-side updated_at
    return unit


async def delete_unit(db: AsyncSession, unit_id: int) -> None:
    """Soft-delete in any status; the code stays reserved on the row but stops scanning.

    Only the automatic codes (unit code and serial) are removed; other barcodes stay
    attached but are hidden by `lookup_barcode` while the unit is in the trash.
    """
    unit = await get_unit(db, unit_id)
    unit.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "unit", unit_id, kind="unit_code")
    if unit.serial_number:
        await db.execute(
            delete(Barcode).where(
                Barcode.code == unit.serial_number,
                Barcode.target_type == "unit",
                Barcode.target_id == unit_id,
                Barcode.kind == "manufacturer",
            )
        )
    await db.flush()


async def unit_out(db: AsyncSession, unit: Unit) -> UnitOut:
    item = await db.get(Item, unit.item_id)  # may be soft-deleted; still shown
    assert item is not None
    specs = await effective_fields(db, item.category_id, scope="unit")
    return UnitOut(
        id=unit.id,
        item_id=unit.item_id,
        item=ItemSummary(id=item.id, name=item.name, sku=item.sku),
        unit_code=unit.unit_code,
        serial_number=unit.serial_number,
        location_id=unit.location_id,
        location_path=await location_path(db, unit.location_id) if unit.location_id else [],
        condition=unit.condition,
        status=unit.status,
        attrs=unit.attrs,
        attrs_display=display_values(specs, unit.attrs),
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


async def get_unit_out(db: AsyncSession, unit_id: int) -> UnitOut:
    return await unit_out(db, await get_unit(db, unit_id))


async def list_units(db: AsyncSession, item_id: int) -> list[Unit]:
    await get_item(db, item_id)
    rows = await db.scalars(
        select(Unit).where(Unit.item_id == item_id, Unit.deleted_at.is_(None)).order_by(Unit.id)
    )
    return list(rows)
