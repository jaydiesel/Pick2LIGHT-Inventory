"""The trash: soft-deleted rows can be listed and restored, and are purged after a retention period.

Services flush but never commit; the caller's session does.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel
from sqlalchemy import delete, exists, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pick2light.core import categories
from pick2light.core.attachments import delete_attachment
from pick2light.core.barcodes import register_barcode, remove_barcodes_for
from pick2light.errors import Conflict, NotFound
from pick2light.models import (
    Attachment,
    Barcode,
    Category,
    CategorySequence,
    FieldDefinition,
    Item,
    Location,
    LogEntry,
    LogEntryType,
    Unit,
)

logger = logging.getLogger(__name__)

TrashType = Literal["category", "log_entry_type", "item", "unit", "location"]
TRASH_TYPES: tuple[str, ...] = get_args(TrashType)

RETENTION_DAYS = 30  # Task 13 replaces this with the `trash.retention_days` setting
PURGE_INTERVAL_SECONDS = 24 * 60 * 60


class TrashEntry(BaseModel):
    type: TrashType
    id: int
    name: str
    deleted_at: datetime


# Table, and the column shown as the entry's name (a unit has no name; its code identifies it).
_SOURCES: dict[str, tuple[Any, str]] = {
    "category": (Category, "name"),
    "log_entry_type": (LogEntryType, "name"),
    "item": (Item, "name"),
    "unit": (Unit, "unit_code"),
    "location": (Location, "name"),
}


async def list_trash(db: AsyncSession) -> list[TrashEntry]:
    """Every soft-deleted row, most recently deleted first."""
    parts = [
        select(
            literal(type_).label("type"),
            model.id.label("id"),
            getattr(model, name_col).label("name"),
            model.deleted_at.label("deleted_at"),
        ).where(model.deleted_at.is_not(None))
        for type_, (model, name_col) in _SOURCES.items()
    ]
    combined = union_all(*parts).subquery()
    rows = await db.execute(
        select(combined).order_by(
            combined.c.deleted_at.desc(), combined.c.type, combined.c.id.desc()
        )
    )
    return [TrashEntry(type=r.type, id=r.id, name=r.name, deleted_at=r.deleted_at) for r in rows]


# --------------------------------------------------------------------------- restore


async def _trashed(db: AsyncSession, model: Any, row_id: int, label: str) -> object:
    row = await db.get(model, row_id)
    if row is None or row.deleted_at is None:
        raise NotFound(f"{label} {row_id} is not in the trash")
    return row


async def _require_alive(db: AsyncSession, model: Any, row_id: int | None, name: str) -> None:
    """A parent the restored row hangs under must not be in the trash itself."""
    if row_id is None:
        return
    parent = await db.get(model, row_id)
    if parent is None or parent.deleted_at is not None:
        shown = getattr(parent, name) if parent is not None else row_id
        raise Conflict(f"Restore '{shown}' first")


async def _claim_codes(
    db: AsyncSession, target_type: str, target_id: int, codes: Sequence[tuple[str, str]]
) -> None:
    """Re-register the automatic codes; nothing is changed unless all of them are free."""
    for code, _ in codes:
        owner = await db.scalar(select(Barcode).where(Barcode.code == code))
        if owner is not None and (owner.target_type, owner.target_id) != (target_type, target_id):
            raise Conflict(
                f"Cannot restore: code {code!r} is now used by another {owner.target_type}; "
                "change or remove that code first"
            )
    for code, kind in codes:
        await register_barcode(db, code, target_type, target_id, kind)


async def _restore_category(db: AsyncSession, category: Category) -> None:
    await _require_alive(db, Category, category.parent_id, "name")
    family = (
        [c.id for c in await categories.ancestors(db, category.parent_id)]
        if (category.parent_id is not None)
        else []
    )
    family += [i for i in await categories.descendant_ids(db, category.id) if i != category.id]
    own_fields = set(
        await db.scalars(
            select(FieldDefinition.key).where(FieldDefinition.category_id == category.id)
        )
    )
    related_fields = set(
        await db.scalars(select(FieldDefinition.key).where(FieldDefinition.category_id.in_(family)))
    )
    if clash := own_fields & related_fields:
        raise Conflict(
            "Field keys already defined in its ancestors or descendants: "
            + ", ".join(sorted(clash))
        )
    own_logs = set(await db.scalars(categories._live_log_keys([category.id])))
    related_logs = set(await db.scalars(categories._live_log_keys(family)))
    if clash := own_logs & related_logs:
        raise Conflict(
            "Log entry type keys already defined in its ancestors or descendants: "
            + ", ".join(sorted(clash))
        )
    category.deleted_at = None


async def _restore_log_type(db: AsyncSession, log_type: LogEntryType) -> None:
    await _require_alive(db, Category, log_type.category_id, "name")
    await categories._check_log_key_free(
        db, log_type.category_id, log_type.key, exclude_id=log_type.id
    )
    log_type.deleted_at = None


async def _restore_item(db: AsyncSession, item: Item) -> None:
    await _require_alive(db, Category, item.category_id, "name")
    await _require_alive(db, Location, item.default_location_id, "name")
    await _claim_codes(db, "item", item.id, [(item.sku, "sku")])
    item.deleted_at = None


async def _restore_unit(db: AsyncSession, unit: Unit) -> None:
    await _require_alive(db, Item, unit.item_id, "name")
    await _require_alive(db, Location, unit.location_id, "name")
    codes = [(unit.unit_code, "unit_code")]
    if unit.serial_number:
        codes.append((unit.serial_number, "manufacturer"))
    await _claim_codes(db, "unit", unit.id, codes)
    unit.deleted_at = None


async def _restore_location(db: AsyncSession, location: Location) -> None:
    await _require_alive(db, Location, location.parent_id, "name")
    await _claim_codes(db, "location", location.id, [(location.code, "location_code")])
    location.deleted_at = None


async def restore(db: AsyncSession, type: TrashType, row_id: int) -> None:
    """Take a row out of the trash, re-checking what create/move would check."""
    if type not in _SOURCES:
        raise NotFound(f"Unknown trash type {type!r}")
    model, _ = _SOURCES[type]
    row = await _trashed(db, model, row_id, type.replace("_", " ").capitalize())
    if isinstance(row, Category):
        await _restore_category(db, row)
    elif isinstance(row, LogEntryType):
        await _restore_log_type(db, row)
    elif isinstance(row, Item):
        await _restore_item(db, row)
    elif isinstance(row, Unit):
        await _restore_unit(db, row)
    else:
        assert isinstance(row, Location)
        await _restore_location(db, row)
    await db.flush()


# --------------------------------------------------------------------------- purge


async def _drop_attachments(
    db: AsyncSession, owner_type: str, owner_ids: Sequence[int], root: Path
) -> None:
    """Delete attachment rows now; their files go after the commit (see delete_attachment)."""
    if not owner_ids:
        return
    ids = await db.scalars(
        select(Attachment.id).where(
            Attachment.owner_type == owner_type, Attachment.owner_id.in_(owner_ids)
        )
    )
    for attachment_id in list(ids):
        await delete_attachment(db, attachment_id, root=root)


async def _drop_log_entries(db: AsyncSession, column: str, owner_id: int, root: Path) -> None:
    entry_ids = list(
        await db.scalars(select(LogEntry.id).where(getattr(LogEntry, column) == owner_id))
    )
    await _drop_attachments(db, "log_entry", entry_ids, root)
    await db.execute(delete(LogEntry).where(LogEntry.id.in_(entry_ids)))


async def _expired(db: AsyncSession, model: Any, cutoff: datetime, *conditions: Any) -> list[int]:
    stmt = select(model.id).where(
        model.deleted_at < cutoff,
        *conditions,
    )
    return list(await db.scalars(stmt.order_by(model.id)))


async def _purge_units(db: AsyncSession, cutoff: datetime, root: Path) -> int:
    ids = await _expired(db, Unit, cutoff)
    for unit_id in ids:
        await _drop_log_entries(db, "unit_id", unit_id, root)
        await _drop_attachments(db, "unit", [unit_id], root)
        await remove_barcodes_for(db, "unit", unit_id)
        await db.execute(delete(Unit).where(Unit.id == unit_id))
    return len(ids)


async def _purge_items(db: AsyncSession, cutoff: datetime, root: Path) -> int:
    # An item that still has unit rows (even consumed ones, which are history) stays.
    ids = await _expired(db, Item, cutoff, ~exists().where(Unit.item_id == Item.id))
    for item_id in ids:
        await _drop_log_entries(db, "item_id", item_id, root)
        await _drop_attachments(db, "item", [item_id], root)
        await remove_barcodes_for(db, "item", item_id)
        # Stock rows and purchase sources go by ON DELETE CASCADE, movements keep a NULL item.
        await db.execute(delete(Item).where(Item.id == item_id))
    return len(ids)


async def _purge_log_types(db: AsyncSession, cutoff: datetime) -> int:
    # A type with entries stays restorable: purging it would destroy history of living things.
    ids = await _expired(
        db, LogEntryType, cutoff, ~exists().where(LogEntry.log_entry_type_id == LogEntryType.id)
    )
    if ids:
        await db.execute(delete(LogEntryType).where(LogEntryType.id.in_(ids)))
    return len(ids)


async def _purge_locations(db: AsyncSession, cutoff: datetime, root: Path) -> int:
    total = 0
    child = Location.__table__.alias("child")
    while ids := await _expired(
        db, Location, cutoff, ~exists().where(child.c.parent_id == Location.id)
    ):
        for location_id in ids:
            await _drop_attachments(db, "location", [location_id], root)
            await remove_barcodes_for(db, "location", location_id)
            await db.execute(delete(Location).where(Location.id == location_id))
        total += len(ids)
    return total


async def _purge_categories(db: AsyncSession, cutoff: datetime, root: Path) -> int:
    total = 0
    child = Category.__table__.alias("child")
    while ids := await _expired(
        db,
        Category,
        cutoff,
        ~exists().where(child.c.parent_id == Category.id),
        ~exists().where(Item.category_id == Category.id),
        ~exists().where(
            LogEntry.log_entry_type_id == LogEntryType.id, LogEntryType.category_id == Category.id
        ),
    ):
        for category_id in ids:
            await _drop_attachments(db, "category", [category_id], root)
            await db.execute(delete(LogEntryType).where(LogEntryType.category_id == category_id))
            await db.execute(
                delete(FieldDefinition).where(FieldDefinition.category_id == category_id)
            )
            await db.execute(
                delete(CategorySequence).where(CategorySequence.category_id == category_id)
            )
            await db.execute(delete(Category).where(Category.id == category_id))
        total += len(ids)
    return total


async def purge_expired(db: AsyncSession, retention_days: int, *, root: Path) -> int:
    """Hard-delete rows that have been in the trash longer than ``retention_days``.

    Returns how many trash rows were removed. Rows still needed by living data are skipped
    and stay restorable: an item that still has unit rows, a log entry type that still has
    entries, a category that still has children, items or log entries, a location with
    sub-locations. ``root`` is the attachments directory; files are removed after commit.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = await _purge_units(db, cutoff, root)
    removed += await _purge_items(db, cutoff, root)
    removed += await _purge_log_types(db, cutoff)
    removed += await _purge_locations(db, cutoff, root)
    removed += await _purge_categories(db, cutoff, root)
    await db.flush()
    return removed


async def purge_loop(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    interval: float = PURGE_INTERVAL_SECONDS,
    retention_days: int = RETENTION_DAYS,
) -> None:
    """Purge once now, then every ``interval`` seconds, until cancelled. Errors are logged."""
    while True:
        try:
            async with factory() as db:
                removed = await purge_expired(db, retention_days, root=root)
                await db.commit()
            if removed:
                logger.info("Trash purge removed %d rows", removed)
        except Exception:
            logger.exception("Trash purge failed")
        await asyncio.sleep(interval)
