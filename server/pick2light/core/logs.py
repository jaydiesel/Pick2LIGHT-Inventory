"""History log entries on units and items, and the latest value per log type.

Services flush but never commit; the request-scoped session commits.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.categories import effective_log_types, get_log_type
from pick2light.core.fields import FieldSpec, display_values, validate_values
from pick2light.core.items import get_item
from pick2light.core.units import get_unit
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from pick2light.models import LogEntry, LogEntryType


class LogEntryIn(BaseModel):
    log_entry_type_id: int
    unit_id: int | None = None
    item_id: int | None = None
    performed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    values: dict[str, Any] = {}
    notes: str | None = None


class LogEntryPatch(BaseModel):
    """The type and target of an entry never change."""

    performed_at: datetime | None = None
    values: dict[str, Any] | None = None
    notes: str | None = None


class LogEntryOut(BaseModel):
    id: int
    log_entry_type_id: int
    type_key: str
    type_name: str
    unit_id: int | None
    item_id: int | None
    performed_at: datetime
    values: dict[str, Any]
    values_display: dict[str, str]
    notes: str | None


class LatestOut(BaseModel):
    performed_at: datetime
    values: dict[str, Any]
    values_display: dict[str, str]


def _specs(log_type: LogEntryType) -> list[FieldSpec]:
    return [FieldSpec.from_dict(f) for f in log_type.fields]


async def _target_category(
    db: AsyncSession, unit_id: int | None, item_id: int | None
) -> tuple[str, int]:
    """("unit" | "item", category id) of the target; exactly one id must be given."""
    if (unit_id is None) == (item_id is None):
        raise ValidationFailed({"unit_id": "Give exactly one of unit_id and item_id"})
    if unit_id is not None:
        unit = await get_unit(db, unit_id)
        item_id = unit.item_id
        kind = "unit"
    else:
        kind = "item"
    assert item_id is not None
    return kind, (await get_item(db, item_id)).category_id


async def add_log_entry(db: AsyncSession, data: LogEntryIn) -> LogEntry:
    kind, category_id = await _target_category(db, data.unit_id, data.item_id)
    log_type = await get_log_type(db, data.log_entry_type_id)
    if log_type.id not in {t.id for t in await effective_log_types(db, category_id)}:
        raise InvalidOperation("This log type does not belong to the category of the target")
    if log_type.applies_to != kind:
        raise InvalidOperation(f"This log type applies to {log_type.applies_to}s, not {kind}s")
    entry = LogEntry(
        log_entry_type_id=log_type.id,
        unit_id=data.unit_id,
        item_id=data.item_id,
        performed_at=data.performed_at,
        values=validate_values(_specs(log_type), data.values),
        notes=data.notes,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def _get_entry(db: AsyncSession, entry_id: int) -> LogEntry:
    entry = await db.get(LogEntry, entry_id)
    if entry is None:
        raise NotFound(f"Log entry {entry_id} not found")
    return entry


async def _type_of(db: AsyncSession, entry: LogEntry) -> LogEntryType:
    log_type = await db.get(LogEntryType, entry.log_entry_type_id)  # may be soft-deleted
    assert log_type is not None
    return log_type


async def update_log_entry(db: AsyncSession, entry_id: int, patch: LogEntryPatch) -> LogEntry:
    entry = await _get_entry(db, entry_id)
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("performed_at", "") is None:
        raise ValidationFailed({"performed_at": "required"})
    if changes.get("values") is not None:
        specs = _specs(await _type_of(db, entry))
        entry.values = validate_values(specs, changes["values"], existing=entry.values)
    if "performed_at" in changes:
        entry.performed_at = changes["performed_at"]
    if "notes" in changes:
        entry.notes = changes["notes"]
    await db.flush()
    await db.refresh(entry)
    return entry


async def delete_log_entry(db: AsyncSession, entry_id: int) -> None:
    """Hard delete; log entries have no trash."""
    await db.delete(await _get_entry(db, entry_id))
    await db.flush()


async def log_entry_out(db: AsyncSession, entry: LogEntry) -> LogEntryOut:
    log_type = await _type_of(db, entry)
    return LogEntryOut(
        id=entry.id,
        log_entry_type_id=entry.log_entry_type_id,
        type_key=log_type.key,
        type_name=log_type.name,
        unit_id=entry.unit_id,
        item_id=entry.item_id,
        performed_at=entry.performed_at,
        values=entry.values,
        values_display=display_values(_specs(log_type), entry.values),
        notes=entry.notes,
    )


async def list_log_entries(
    db: AsyncSession, *, unit_id: int | None = None, item_id: int | None = None
) -> list[LogEntryOut]:
    """Newest first. Entries of soft-deleted log types are still listed."""
    await _target_category(db, unit_id, item_id)  # validates the target
    query = select(LogEntry).order_by(LogEntry.performed_at.desc(), LogEntry.id.desc())
    query = query.where(
        LogEntry.unit_id == unit_id if unit_id is not None else LogEntry.item_id == item_id
    )
    rows = await db.scalars(query)
    return [await log_entry_out(db, e) for e in rows]


async def latest_values(
    db: AsyncSession, *, unit_id: int | None = None, item_id: int | None = None
) -> dict[str, LatestOut]:
    """Newest entry per log type key, reduced to the type's summary fields.

    Soft-deleted log types are skipped.
    """
    await _target_category(db, unit_id, item_id)
    view, column, target = (
        ("unit_latest_values", "unit_id", unit_id)
        if unit_id is not None
        else ("item_latest_values", "item_id", item_id)
    )
    rows = (
        await db.execute(
            text(
                f'SELECT v.log_entry_type_id, v.type_key, v.performed_at, v."values" '  # noqa: S608
                f"FROM {view} v JOIN log_entry_type t ON t.id = v.log_entry_type_id "
                f"WHERE v.{column} = :target AND t.deleted_at IS NULL ORDER BY v.type_key"
            ),
            {"target": target},
        )
    ).all()
    out: dict[str, LatestOut] = {}
    for type_id, key, performed_at, values in rows:
        log_type = await db.get(LogEntryType, type_id)
        assert log_type is not None
        summary = set(log_type.summary_fields)
        specs = [s for s in _specs(log_type) if s.key in summary]
        shown = {k: v for k, v in values.items() if k in summary}
        out[key] = LatestOut(
            performed_at=performed_at, values=shown, values_display=display_values(specs, shown)
        )
    return out
