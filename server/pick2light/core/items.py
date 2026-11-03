"""Items: products / SKUs with custom field values stored as JSONB.

Services flush but never commit; the request-scoped session commits.
"""

import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import code_exists, register_barcode, remove_barcodes_for
from pick2light.core.categories import (
    PathItem,
    ancestors,
    effective_fields,
    effective_tracking_mode,
    get_category,
)
from pick2light.core.fields import display_values, text_values, validate_values
from pick2light.core.locations import get_location
from pick2light.core.sku import ensure_unique_code, generate_sku, next_sequence, sanitize_code
from pick2light.errors import Conflict, InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Item, Stock, Unit

ACTIVE_UNIT_STATUSES = ("in_stock", "checked_out")


class ItemIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=300)
    sku: str | None = Field(default=None, max_length=200)
    description: str | None = None
    notes: str | None = None
    attrs: dict[str, Any] = {}
    min_stock: int | None = Field(default=None, ge=0)
    default_location_id: int | None = None


class ItemPatch(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    sku: str | None = Field(default=None, max_length=200)
    description: str | None = None
    notes: str | None = None
    attrs: dict[str, Any] | None = None
    min_stock: int | None = Field(default=None, ge=0)
    default_location_id: int | None = None


class ItemOut(BaseModel):
    id: int
    category_id: int
    category_path: list[PathItem]
    name: str
    sku: str
    description: str | None
    notes: str | None
    attrs: dict[str, Any]
    attrs_display: dict[str, str]
    min_stock: int | None
    default_location_id: int | None
    photo_attachment_id: int | None
    tracking_mode: str
    on_hand: float
    created_at: datetime
    updated_at: datetime


async def get_item(db: AsyncSession, item_id: int) -> Item:
    item = await db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound(f"Item {item_id} not found")
    return item


async def sku_taken(db: AsyncSession, code: str) -> bool:
    """A SKU is taken by a barcode or by any item row, soft-deleted ones included."""
    if await code_exists(db, code):
        return True
    return await db.scalar(select(Item.id).where(Item.sku == code).limit(1)) is not None


def _manual_sku(raw: str) -> str:
    code = sanitize_code(raw.strip()).upper()
    if not code:
        raise ValidationFailed({"sku": "must contain letters, digits, '.', '_' or '-'"})
    return code


async def _check_default_location(db: AsyncSession, location_id: int | None) -> None:
    if location_id is None:
        return
    try:
        await get_location(db, location_id)
    except NotFound:
        raise ValidationFailed({"default_location_id": "Location not found"}) from None


async def refresh_search_text(db: AsyncSession, item: Item) -> None:
    """Rebuild `search_text` (and so the generated `search_vector`) from the item's state."""
    specs = await effective_fields(db, item.category_id, scope="item")
    parts = [item.name, item.sku, item.description or "", *text_values(specs, item.attrs)]
    item.search_text = unicodedata.normalize("NFKC", " ".join(p for p in parts if p))
    await db.flush()


async def create_item(db: AsyncSession, data: ItemIn) -> Item:
    await get_category(db, data.category_id)
    await _check_default_location(db, data.default_location_id)
    specs = await effective_fields(db, data.category_id, scope="item")
    attrs = validate_values(specs, data.attrs, scope="item")
    if data.sku and data.sku.strip():
        code = _manual_sku(data.sku)
    else:
        code = await generate_sku(db, data.category_id, attrs)
        if not code:  # e.g. a pattern made only of empty field values
            seq = await next_sequence(db, data.category_id, "sku")
            code = f"ITEM-{seq:04d}"
    sku = await ensure_unique_code(code, lambda c: sku_taken(db, c))
    item = Item(
        category_id=data.category_id,
        name=data.name,
        sku=sku,
        description=data.description,
        notes=data.notes,
        attrs=attrs,
        min_stock=data.min_stock,
        default_location_id=data.default_location_id,
    )
    db.add(item)
    await db.flush()
    await register_barcode(db, sku, "item", item.id, "sku")
    await refresh_search_text(db, item)
    await db.refresh(item)  # picks up the server-side updated_at
    return item


async def _change_category(
    db: AsyncSession, item: Item, category_id: int, attr_changes: dict[str, Any] | None
) -> dict[str, Any]:
    """Attrs for the new category: stale keys dropped, everything re-validated."""
    await get_category(db, category_id)
    old_mode = await effective_tracking_mode(db, item.category_id)
    if old_mode != await effective_tracking_mode(db, category_id):
        has_units = await db.scalar(
            select(Unit.id).where(Unit.item_id == item.id, Unit.deleted_at.is_(None)).limit(1)
        )
        if has_units is not None or await bulk_quantity(db, item.id) > 0:
            raise InvalidOperation(
                "Cannot move an item with stock or units between bulk and unit tracked categories"
            )
    specs = await effective_fields(db, category_id, scope="item")
    keys = {s.key for s in specs}
    carried = {k: v for k, v in item.attrs.items() if k in keys}
    carried.update(attr_changes or {})
    return validate_values(specs, carried, scope="item")


async def update_item(db: AsyncSession, item_id: int, patch: ItemPatch) -> Item:
    item = await get_item(db, item_id)
    changes = patch.model_dump(exclude_unset=True)
    for required in ("category_id", "name"):
        if required in changes and changes[required] is None:
            raise ValidationFailed({required: "required"})
    if "default_location_id" in changes:
        await _check_default_location(db, changes["default_location_id"])

    new_sku = changes.pop("sku", None)
    new_category = changes.pop("category_id", None)
    attr_changes = changes.pop("attrs", None)
    if new_category is not None and new_category != item.category_id:
        item.attrs = await _change_category(db, item, new_category, attr_changes)
        item.category_id = new_category
    elif attr_changes is not None:
        specs = await effective_fields(db, item.category_id, scope="item")
        item.attrs = validate_values(specs, attr_changes, existing=item.attrs, scope="item")
    for key, value in changes.items():
        setattr(item, key, value)

    if new_sku is not None and new_sku.strip():
        sku = _manual_sku(new_sku)
        if sku != item.sku:
            if await sku_taken(db, sku):
                raise Conflict(f"Code {sku!r} is already in use")
            await remove_barcodes_for(db, "item", item.id, kind="sku")
            item.sku = sku
            await db.flush()
            await register_barcode(db, sku, "item", item.id, "sku")
    await db.flush()
    await refresh_search_text(db, item)
    await db.refresh(item)  # picks up the server-side updated_at
    return item


async def bulk_quantity(db: AsyncSession, item_id: int) -> float:
    """Total bulk quantity across all locations."""
    total = await db.scalar(
        select(func.coalesce(func.sum(Stock.quantity), 0)).where(Stock.item_id == item_id)
    )
    return float(total or 0)


async def on_hand(db: AsyncSession, item_id: int, mode: str) -> float:
    if mode == "unit":
        count = await db.scalar(
            select(func.count())
            .select_from(Unit)
            .where(Unit.item_id == item_id, Unit.deleted_at.is_(None), Unit.status == "in_stock")
        )
        return float(count or 0)
    return await bulk_quantity(db, item_id)


async def delete_item(db: AsyncSession, item_id: int) -> None:
    """Soft-delete; refused while any stock remains. The SKU stays reserved on the row."""
    item = await get_item(db, item_id)
    active = await db.scalar(
        select(func.count())
        .select_from(Unit)
        .where(
            Unit.item_id == item_id,
            Unit.deleted_at.is_(None),
            Unit.status.in_(ACTIVE_UNIT_STATUSES),
        )
    )
    if active or await bulk_quantity(db, item_id) > 0:
        raise Conflict("Item still has stock; consume or remove it first")
    item.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "item", item_id)
    await db.flush()


async def item_out(db: AsyncSession, item: Item) -> ItemOut:
    mode = await effective_tracking_mode(db, item.category_id)
    specs = await effective_fields(db, item.category_id, scope="item")
    return ItemOut(
        id=item.id,
        category_id=item.category_id,
        category_path=[
            PathItem(id=c.id, name=c.name) for c in await ancestors(db, item.category_id)
        ],
        name=item.name,
        sku=item.sku,
        description=item.description,
        notes=item.notes,
        attrs=item.attrs,
        attrs_display=display_values(specs, item.attrs),
        min_stock=item.min_stock,
        default_location_id=item.default_location_id,
        photo_attachment_id=item.photo_attachment_id,
        tracking_mode=mode,
        on_hand=await on_hand(db, item.id, mode),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def get_item_out(db: AsyncSession, item_id: int) -> ItemOut:
    return await item_out(db, await get_item(db, item_id))
