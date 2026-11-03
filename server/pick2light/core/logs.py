"""History log entries and latest values (spec §3.2 `log_entry`)."""

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core.fields import FieldSpec, display_values, validate_values
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import Item, LogEntry, LogEntryType, Unit


class LogEntryIn(BaseModel):
    log_entry_type_id: int
    unit_id: int | None = None
    item_id: int | None = None
    performed_at: datetime | None = None
    values: dict = {}
    notes: str | None = None


class LogEntryPatch(BaseModel):
    performed_at: datetime | None = None
    values: dict | None = None
    notes: str | None = None


class LogEntryOut(BaseModel):
    id: int
    log_entry_type_id: int
    type_key: str
    type_name: str
    unit_id: int | None
    item_id: int | None
    performed_at: datetime
    values: dict
    values_display: dict[str, str]
    notes: str | None
    created_at: datetime


class LatestOut(BaseModel):
    performed_at: datetime
    values: dict
    values_display: dict[str, str]


def type_specs(lt: LogEntryType) -> list[FieldSpec]:
    return [FieldSpec.from_dict(f) for f in lt.fields or []]


async def _type(db: AsyncSession, type_id: int) -> LogEntryType:
    lt = await db.get(LogEntryType, type_id)
    if lt is None:
        raise NotFound(f"Log entry type {type_id} not found")
    return lt


async def _target_category(db: AsyncSession, unit_id: int | None, item_id: int | None) -> int:
    if unit_id is not None:
        unit = await db.get(Unit, unit_id)
        if unit is None or unit.deleted_at is not None:
            raise NotFound(f"Unit {unit_id} not found")
        item_id = unit.item_id
    item = await db.get(Item, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound(f"Item {item_id} not found")
    return item.category_id


async def add_log_entry(db: AsyncSession, data: LogEntryIn) -> LogEntry:
    if (data.unit_id is None) == (data.item_id is None):
        raise ValidationFailed({"unit_id": "Choose either a unit or an item"})
    lt = await _type(db, data.log_entry_type_id)
    if lt.deleted_at is not None:
        raise InvalidOperation(f"'{lt.name}' has been deleted")
    category_id = await _target_category(db, data.unit_id, data.item_id)
    if lt.id not in {t.id for t in await cats.effective_log_types(db, category_id)}:
        raise InvalidOperation(f"'{lt.name}' isn't available for this category")
    target = "unit" if data.unit_id is not None else "item"
    if lt.applies_to != target:
        raise InvalidOperation(f"'{lt.name}' is recorded per {lt.applies_to}, not per {target}")
    values = validate_values(type_specs(lt), data.values)
    entry = LogEntry(
        log_entry_type_id=lt.id,
        unit_id=data.unit_id,
        item_id=data.item_id,
        performed_at=data.performed_at or datetime.now(UTC),
        values=values,
        notes=data.notes,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_log_entry(db: AsyncSession, entry_id: int) -> LogEntry:
    entry = await db.get(LogEntry, entry_id)
    if entry is None:
        raise NotFound(f"Log entry {entry_id} not found")
    return entry


async def update_log_entry(db: AsyncSession, entry_id: int, patch: LogEntryPatch) -> LogEntry:
    entry = await get_log_entry(db, entry_id)
    lt = await _type(db, entry.log_entry_type_id)
    if patch.values is not None:
        entry.values = validate_values(type_specs(lt), patch.values, existing=entry.values)
    if patch.performed_at is not None:
        entry.performed_at = patch.performed_at
    if "notes" in patch.model_fields_set:
        entry.notes = patch.notes
    await db.flush()
    return entry


async def delete_log_entry(db: AsyncSession, entry_id: int) -> None:
    await db.delete(await get_log_entry(db, entry_id))
    await db.flush()


async def to_out(db: AsyncSession, entry: LogEntry) -> LogEntryOut:
    lt = await _type(db, entry.log_entry_type_id)
    return LogEntryOut(
        id=entry.id,
        log_entry_type_id=lt.id,
        type_key=lt.key,
        type_name=lt.name,
        unit_id=entry.unit_id,
        item_id=entry.item_id,
        performed_at=entry.performed_at,
        values=entry.values or {},
        values_display=display_values(type_specs(lt), entry.values or {}),
        notes=entry.notes,
        created_at=entry.created_at,
    )


async def list_log_entries(
    db: AsyncSession, *, unit_id: int | None = None, item_id: int | None = None
) -> list[LogEntryOut]:
    q = select(LogEntry).order_by(LogEntry.performed_at.desc(), LogEntry.id.desc())
    q = q.where(LogEntry.unit_id == unit_id) if unit_id is not None else q.where(LogEntry.item_id == item_id)
    return [await to_out(db, e) for e in await db.scalars(q)]


async def latest_values(
    db: AsyncSession, *, unit_id: int | None = None, item_id: int | None = None
) -> dict[str, LatestOut]:
    kind, target = ("unit", unit_id) if unit_id is not None else ("item", item_id)
    rows = await db.execute(
        text(
            f"SELECT log_entry_type_id, type_key, performed_at, values FROM {kind}_latest_values WHERE {kind}_id = :id"
        ),
        {"id": target},
    )
    out: dict[str, LatestOut] = {}
    for type_id, key, performed_at, values in rows:
        lt = await _type(db, type_id)
        if lt.deleted_at is not None:
            continue
        specs = [s for s in type_specs(lt) if s.key in (lt.summary_fields or [])]
        summary = {k: v for k, v in (values or {}).items() if k in (lt.summary_fields or [])}
        out[key] = LatestOut(
            performed_at=performed_at, values=summary, values_display=display_values(specs, summary)
        )
    return out
