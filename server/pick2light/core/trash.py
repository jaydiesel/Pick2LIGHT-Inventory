"""Trash: soft-deleted rows, restore and retention purge (spec §4.5)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cat_svc
from pick2light.core.attachments import delete_attachment, list_attachments
from pick2light.core.barcodes import register_barcode, remove_barcodes_for
from pick2light.errors import Conflict, NotFound
from pick2light.models import Category, Item, Location, LogEntry, LogEntryType, Stock, Unit

TrashType = Literal["category", "log_entry_type", "item", "unit", "location"]
_MODELS: dict[str, Any] = {
    "category": Category,
    "log_entry_type": LogEntryType,
    "item": Item,
    "unit": Unit,
    "location": Location,
}


class TrashEntry(BaseModel):
    type: TrashType
    id: int
    name: str
    deleted_at: datetime


def _name(type_: str, row: Any) -> str:
    return str(row.unit_code if type_ == "unit" else row.name)


async def list_trash(db: AsyncSession) -> list[TrashEntry]:
    out: list[TrashEntry] = []
    for type_, model in _MODELS.items():
        rows = await db.scalars(select(model).where(model.deleted_at.is_not(None)))  # type: ignore[attr-defined]
        out.extend(
            TrashEntry(type=type_, id=r.id, name=_name(type_, r), deleted_at=r.deleted_at) for r in rows
        )  # type: ignore[arg-type]
    return sorted(out, key=lambda e: e.deleted_at, reverse=True)


async def _deleted(db: AsyncSession, type_: str, row_id: int) -> Any:
    model = _MODELS[type_]
    row = await db.get(model, row_id)
    if row is None or row.deleted_at is None:
        raise NotFound(f"Nothing in the trash for {type_} {row_id}")
    return row


async def _alive(db: AsyncSession, model: Any, row_id: int | None) -> None:
    """Refuse restoring a row whose parent is still in the trash."""
    if row_id is None:
        return
    row = await db.get(model, row_id)
    if row is None or row.deleted_at is not None:
        label = getattr(row, "name", None) or getattr(row, "unit_code", None) or str(row_id)
        raise Conflict(f"Restore '{label}' first")


async def restore(db: AsyncSession, type_: TrashType, row_id: int) -> None:
    row = await _deleted(db, type_, row_id)
    if type_ == "category":
        await _alive(db, Category, row.parent_id)
        cats = await cat_svc._all(db)
        cats[row.id] = row
        family = [c for c in cat_svc._related_ids(cats, row.id) if c != row.id]
        own_fields = await cat_svc._field_keys(db, [row.id])
        clash = own_fields & await cat_svc._field_keys(db, family)
        if clash:
            raise Conflict(
                f"Field key '{sorted(clash)[0]}' now exists in a related category; rename one first"
            )
        log_clash = await cat_svc._log_type_keys(db, [row.id]) & await cat_svc._log_type_keys(db, family)
        if log_clash:
            raise Conflict(f"Log type '{sorted(log_clash)[0]}' now exists in a related category")
    elif type_ == "log_entry_type":
        await _alive(db, Category, row.category_id)
        family = cat_svc._related_ids(await cat_svc._all(db), row.category_id)
        if row.key in await cat_svc._log_type_keys(db, family):
            raise Conflict(f"Another log type in this category family now uses the key '{row.key}'")
    elif type_ == "item":
        await _alive(db, Category, row.category_id)
        row.deleted_at = None
        await db.flush()
        await register_barcode(db, row.sku, "item", row.id, "sku")
        return
    elif type_ == "unit":
        await _alive(db, Item, row.item_id)
        await _alive(db, Location, row.location_id)
        row.deleted_at = None
        await db.flush()
        await register_barcode(db, row.unit_code, "unit", row.id, "unit_code")
        if row.serial_number:
            await register_barcode(db, row.serial_number, "unit", row.id, "manufacturer")
        return
    elif type_ == "location":
        await _alive(db, Location, row.parent_id)
        row.deleted_at = None
        await db.flush()
        await register_barcode(db, row.code, "location", row.id, "location_code")
        return
    row.deleted_at = None
    await db.flush()


async def _drop_attachments(db: AsyncSession, owner_type: str, owner_id: int, root: Path) -> None:
    for att in await list_attachments(db, owner_type, owner_id):
        await delete_attachment(db, att.id, root=root)


async def _purge_unit(db: AsyncSession, unit: Unit, root: Path) -> None:
    await remove_barcodes_for(db, "unit", unit.id)
    await _drop_attachments(db, "unit", unit.id, root)
    await db.delete(unit)
    await db.flush()


async def purge_expired(db: AsyncSession, retention_days: int, *, root: Path) -> int:
    """Hard-delete rows that have been in the trash longer than retention_days."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    purged = 0

    for unit in list(await db.scalars(select(Unit).where(Unit.deleted_at < cutoff))):
        await _purge_unit(db, unit, root)
        purged += 1

    for item in list(await db.scalars(select(Item).where(Item.deleted_at < cutoff))):
        for unit in list(await db.scalars(select(Unit).where(Unit.item_id == item.id))):
            await _purge_unit(db, unit, root)
        await remove_barcodes_for(db, "item", item.id)
        await _drop_attachments(db, "item", item.id, root)
        await db.delete(item)
        await db.flush()
        purged += 1

    for lt in list(await db.scalars(select(LogEntryType).where(LogEntryType.deleted_at < cutoff))):
        has_history = await db.scalar(select(LogEntry.id).where(LogEntry.log_entry_type_id == lt.id).limit(1))
        if has_history:
            continue  # never destroy recorded tests; the type stays restorable in the trash
        await db.delete(lt)
        await db.flush()
        purged += 1

    while True:  # leaves first, so parents become purgeable
        cats = list(await db.scalars(select(Category).where(Category.deleted_at < cutoff)))
        progress = False
        for cat in cats:
            children = await db.scalar(
                select(func.count()).select_from(Category).where(Category.parent_id == cat.id)
            )
            items = await db.scalar(select(func.count()).select_from(Item).where(Item.category_id == cat.id))
            types = await db.scalar(
                select(func.count()).select_from(LogEntryType).where(LogEntryType.category_id == cat.id)
            )
            if children or items or types:
                continue
            await _drop_attachments(db, "category", cat.id, root)
            await db.delete(cat)
            await db.flush()
            purged += 1
            progress = True
        if not progress:
            break

    while True:
        locs = list(await db.scalars(select(Location).where(Location.deleted_at < cutoff)))
        progress = False
        for loc in locs:
            children = await db.scalar(
                select(func.count()).select_from(Location).where(Location.parent_id == loc.id)
            )
            held = await db.scalar(
                select(func.coalesce(func.sum(Stock.quantity), 0)).where(Stock.location_id == loc.id)
            )
            if children or (held and float(held) > 0):
                continue
            await db.execute(delete(Stock).where(Stock.location_id == loc.id))
            await remove_barcodes_for(db, "location", loc.id)
            await _drop_attachments(db, "location", loc.id, root)
            await db.delete(loc)
            await db.flush()
            purged += 1
            progress = True
        if not progress:
            break
    return purged
