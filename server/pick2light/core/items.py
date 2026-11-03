"""Items: products / SKUs (spec §3.2)."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core.barcodes import BarcodeOut, barcodes_for, register_barcode, remove_barcodes_for
from pick2light.core.categories import PathRef
from pick2light.core.fields import display_values, text_values, validate_values
from pick2light.core.sku import ensure_unique_code, generate_sku, sanitize_code
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Barcode, Item, Location, Unit


class ItemIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=300)
    sku: str | None = Field(default=None, max_length=120)
    description: str | None = None
    notes: str | None = None
    attrs: dict = {}
    min_stock: int | None = Field(default=None, ge=0)
    default_location_id: int | None = None


class ItemPatch(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    sku: str | None = Field(default=None, max_length=120)
    description: str | None = None
    notes: str | None = None
    attrs: dict | None = None
    min_stock: int | None = Field(default=None, ge=0)
    default_location_id: int | None = None
    photo_attachment_id: int | None = None


class ItemSummary(BaseModel):
    id: int
    name: str
    sku: str


class ItemOut(BaseModel):
    id: int
    category_id: int
    category_path: list[PathRef]
    tracking_mode: str
    name: str
    sku: str
    description: str | None
    notes: str | None
    attrs: dict
    attrs_display: dict[str, str]
    min_stock: int | None
    default_location_id: int | None
    photo_attachment_id: int | None
    on_hand: float
    barcodes: list[BarcodeOut]
    created_at: datetime
    updated_at: datetime


async def get_item(db: AsyncSession, item_id: int) -> Item:
    item = await db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound(f"Item {item_id} not found")
    return item


async def sku_taken(db: AsyncSession, code: str, exclude_item: int | None = None) -> bool:
    bc = await db.scalar(select(Barcode).where(Barcode.code == code))
    if bc is not None and not (bc.target_type == "item" and bc.target_id == exclude_item):
        return True
    other = await db.scalar(select(Item.id).where(Item.sku == code))
    return other is not None and other != exclude_item


async def _unique_sku(db: AsyncSession, raw: str, exclude_item: int | None = None) -> str:
    clean = sanitize_code(raw)
    if not clean:
        raise ValidationFailed({"sku": "Use letters, digits, '.', '_' or '-'"})

    async def exists(code: str) -> bool:
        return await sku_taken(db, code, exclude_item)

    return await ensure_unique_code(clean, exists)


async def _check_location(
    db: AsyncSession, location_id: int | None, field: str = "default_location_id"
) -> None:
    if location_id is None:
        return
    loc = await db.get(Location, location_id)
    if loc is None or loc.deleted_at is not None:
        raise ValidationFailed({field: "Unknown location"})


async def refresh_search_text(db: AsyncSession, item: Item) -> None:
    specs = await cats.effective_fields(db, item.category_id, scope="item")
    parts = [item.name, item.sku, item.description or "", *text_values(specs, item.attrs or {})]
    item.search_text = " ".join(p for p in parts if p)


async def on_hand(db: AsyncSession, item: Item) -> float:
    mode = await cats.effective_tracking_mode(db, item.category_id)
    if mode == "unit":
        count = await db.scalar(
            select(func.count())
            .select_from(Unit)
            .where(Unit.item_id == item.id, Unit.status == "in_stock", Unit.deleted_at.is_(None))
        )
        return float(count or 0)
    return 0.0


async def _has_active_stock(db: AsyncSession, item: Item) -> bool:
    if await on_hand(db, item) > 0:
        return True
    active = await db.scalar(
        select(func.count())
        .select_from(Unit)
        .where(
            Unit.item_id == item.id,
            Unit.deleted_at.is_(None),
            or_(Unit.status == "in_stock", Unit.status == "checked_out"),
        )
    )
    return bool(active)


async def create_item(db: AsyncSession, data: ItemIn) -> Item:
    await cats.get_category(db, data.category_id)
    specs = await cats.effective_fields(db, data.category_id, scope="item")
    attrs = validate_values(specs, data.attrs, scope="item")
    await _check_location(db, data.default_location_id)
    raw_sku = data.sku if data.sku and data.sku.strip() else await generate_sku(db, data.category_id, attrs)
    sku = await _unique_sku(db, raw_sku)
    item = Item(
        category_id=data.category_id,
        name=data.name.strip(),
        sku=sku,
        description=data.description,
        notes=data.notes,
        attrs=attrs,
        min_stock=data.min_stock,
        default_location_id=data.default_location_id,
    )
    await refresh_search_text(db, item)
    db.add(item)
    await db.flush()
    await register_barcode(db, sku, "item", item.id, "sku")
    return item


async def update_item(db: AsyncSession, item_id: int, patch: ItemPatch) -> Item:
    item = await get_item(db, item_id)
    sent = patch.model_fields_set
    if "category_id" in sent and patch.category_id is not None and patch.category_id != item.category_id:
        await cats.get_category(db, patch.category_id)
        old_mode = await cats.effective_tracking_mode(db, item.category_id)
        new_mode = await cats.effective_tracking_mode(db, patch.category_id)
        if old_mode != new_mode and await _has_active_stock(db, item):
            raise Conflict("The new category tracks stock differently; empty this item's stock first")
        specs = await cats.effective_fields(db, patch.category_id, scope="item")
        keys = {s.key for s in specs}
        carried = {k: v for k, v in (item.attrs or {}).items() if k in keys}
        item.attrs = validate_values(specs, {**carried, **(patch.attrs or {})}, scope="item")
        item.category_id = patch.category_id
    elif patch.attrs is not None:
        specs = await cats.effective_fields(db, item.category_id, scope="item")
        item.attrs = validate_values(specs, patch.attrs, existing=item.attrs, scope="item")
    if "sku" in sent and patch.sku and patch.sku != item.sku:
        new_sku = await _unique_sku(db, patch.sku, exclude_item=item.id)
        await remove_barcodes_for(db, "item", item.id, kind="sku")
        item.sku = new_sku
        await db.flush()
        await register_barcode(db, new_sku, "item", item.id, "sku")
    if "default_location_id" in sent:
        await _check_location(db, patch.default_location_id)
        item.default_location_id = patch.default_location_id
    if patch.name is not None:
        item.name = patch.name.strip()
    for attr in ("description", "notes", "min_stock", "photo_attachment_id"):
        if attr in sent:
            setattr(item, attr, getattr(patch, attr))
    await refresh_search_text(db, item)
    await db.flush()
    return item


async def delete_item(db: AsyncSession, item_id: int) -> None:
    item = await get_item(db, item_id)
    if await _has_active_stock(db, item):
        raise Conflict(f"'{item.name}' still has stock; check it out or move it first")
    item.deleted_at = datetime.now(UTC)
    await remove_barcodes_for(db, "item", item.id)
    await db.flush()


async def get_item_out(db: AsyncSession, item_id: int) -> ItemOut:
    item = await get_item(db, item_id)
    await db.refresh(item)
    chain = await cats.ancestors(db, item.category_id)
    specs = await cats.effective_fields(db, item.category_id, scope="item")
    return ItemOut(
        id=item.id,
        category_id=item.category_id,
        category_path=[PathRef(id=c.id, name=c.name) for c in chain],
        tracking_mode=await cats.effective_tracking_mode(db, item.category_id),
        name=item.name,
        sku=item.sku,
        description=item.description,
        notes=item.notes,
        attrs=item.attrs or {},
        attrs_display=display_values(specs, item.attrs or {}),
        min_stock=item.min_stock,
        default_location_id=item.default_location_id,
        photo_attachment_id=item.photo_attachment_id,
        on_hand=await on_hand(db, item),
        barcodes=[BarcodeOut.model_validate(b) for b in await barcodes_for(db, "item", item.id)],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def summary(item: Item) -> ItemSummary:
    return ItemSummary(id=item.id, name=item.name, sku=item.sku)
