"""CSV import/export and the full JSON export.

Services flush but never commit; the request-scoped session commits. Previews run the
real import inside a SAVEPOINT that is rolled back, so generated SKUs, unit codes and
validation behave exactly as they will on apply.
"""

import csv
import io
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from decimal import Decimal
from decimal import InvalidOperation as DecimalError
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.barcodes import register_barcode
from pick2light.core.categories import effective_fields, effective_tracking_mode, get_category
from pick2light.core.fields import FieldSpec, validate_values
from pick2light.core.items import ItemIn, ItemPatch, create_item, update_item
from pick2light.core.locations import get_location
from pick2light.core.sku import sanitize_code
from pick2light.core.stock import add_stock
from pick2light.core.units import UnitIn, create_unit, unit_code_taken
from pick2light.errors import AppError, NotFound, ValidationFailed
from pick2light.models import (
    Attachment,
    Barcode,
    Category,
    CategorySequence,
    FieldDefinition,
    Item,
    Location,
    LocationType,
    LogEntry,
    LogEntryType,
    PurchaseSource,
    Setting,
    Stock,
    StockMovement,
    Unit,
)
from pick2light.models.inventory import UNIT_CONDITIONS

logger = logging.getLogger(__name__)

Entity = Literal["items", "units", "locations", "stock", "log_entries"]
PATH_SEP = " / "
BOM = "﻿"
LIST_SEP = "|"

# --------------------------------------------------------------------------- cell formatting


def _number_text(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    text = format(Decimal(repr(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def cell(value: Any) -> str:
    """Raw stored value as a CSV cell (lists joined by `|`, booleans `true`/`false`)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _number_text(value)
    if isinstance(value, list):
        return LIST_SEP.join(cell(v) for v in value)
    return str(value)


def _line(values: Sequence[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(values)
    return buffer.getvalue()


# --------------------------------------------------------------------------- export


def _attr_keys(rows: Sequence[dict[str, Any]], prefix: str) -> list[str]:
    return [f"{prefix}.{k}" for k in sorted({k for attrs in rows for k in attrs})]


async def _category_paths(db: AsyncSession) -> dict[int, str]:
    cats = {c.id: c for c in await db.scalars(select(Category))}

    def path(cid: int) -> str:
        names: list[str] = []
        node: Category | None = cats.get(cid)
        while node is not None:
            names.append(node.name)
            node = cats.get(node.parent_id) if node.parent_id else None
        return PATH_SEP.join(reversed(names))

    return {cid: path(cid) for cid in cats}


async def _location_info(db: AsyncSession) -> tuple[dict[int, Location], dict[int, str]]:
    locs = {loc.id: loc for loc in await db.scalars(select(Location))}

    def path(lid: int) -> str:
        names: list[str] = []
        node: Location | None = locs.get(lid)
        while node is not None:
            names.append(node.name)
            node = locs.get(node.parent_id) if node.parent_id else None
        return PATH_SEP.join(reversed(names))

    return locs, {lid: path(lid) for lid in locs}


async def _export_items(db: AsyncSession) -> AsyncIterator[list[str]]:
    paths = await _category_paths(db)
    locs, _ = await _location_info(db)
    items = list(await db.scalars(select(Item).where(Item.deleted_at.is_(None)).order_by(Item.id)))
    bulk = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Stock.item_id, func.sum(Stock.quantity)).group_by(Stock.item_id)
            )
        ).all()
    }
    units = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Unit.item_id, func.count())
                .where(Unit.deleted_at.is_(None), Unit.status == "in_stock")
                .group_by(Unit.item_id)
            )
        ).all()
    }
    modes: dict[int, str] = {}
    keys = _attr_keys([i.attrs for i in items], "attr")
    yield [
        "id", "sku", "name", "category_path", "description", "notes",
        "min_stock", "default_location_code", "on_hand", *keys,
    ]  # fmt: skip
    for item in items:
        if item.category_id not in modes:
            modes[item.category_id] = await effective_tracking_mode(db, item.category_id)
        on_hand = (
            units.get(item.id, 0) if modes[item.category_id] == "unit" else bulk.get(item.id, 0)
        )
        default_loc = locs.get(item.default_location_id) if item.default_location_id else None
        yield [
            str(item.id),
            item.sku,
            item.name,
            paths.get(item.category_id, ""),
            item.description or "",
            item.notes or "",
            cell(item.min_stock),
            default_loc.code if default_loc else "",
            _number_text(float(on_hand)),
            *(cell(item.attrs.get(k.removeprefix("attr."))) for k in keys),
        ]


async def _export_units(db: AsyncSession) -> AsyncIterator[list[str]]:
    locs, _ = await _location_info(db)
    skus = {i.id: i.sku for i in await db.scalars(select(Item))}
    units = list(await db.scalars(select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id)))
    keys = _attr_keys([u.attrs for u in units], "attr")
    yield [
        "id",
        "unit_code",
        "item_sku",
        "serial_number",
        "location_code",
        "condition",
        "status",
        *keys,
    ]
    for unit in units:
        loc = locs.get(unit.location_id) if unit.location_id else None
        yield [
            str(unit.id),
            unit.unit_code,
            skus.get(unit.item_id, ""),
            unit.serial_number or "",
            loc.code if loc else "",
            unit.condition,
            unit.status,
            *(cell(unit.attrs.get(k.removeprefix("attr."))) for k in keys),
        ]


async def _export_locations(db: AsyncSession) -> AsyncIterator[list[str]]:
    locs, paths = await _location_info(db)
    types = {t.id: t.name for t in await db.scalars(select(LocationType))}
    yield ["id", "code", "name", "path", "type", "parent_code"]
    for loc in sorted(locs.values(), key=lambda x: x.id):
        if loc.deleted_at is not None:
            continue
        parent = locs.get(loc.parent_id) if loc.parent_id else None
        yield [
            str(loc.id),
            loc.code,
            loc.name,
            paths[loc.id],
            types.get(loc.location_type_id, "") if loc.location_type_id else "",
            parent.code if parent else "",
        ]


async def _export_stock(db: AsyncSession) -> AsyncIterator[list[str]]:
    rows = await db.execute(
        select(Item.sku, Location.code, Stock.quantity)
        .join(Item, Item.id == Stock.item_id)
        .join(Location, Location.id == Stock.location_id)
        .where(Item.deleted_at.is_(None), Location.deleted_at.is_(None), Stock.quantity > 0)
        .order_by(Stock.id)
    )
    yield ["item_sku", "location_code", "quantity"]
    for sku, code, quantity in rows.all():
        yield [sku, code, _number_text(float(quantity))]


async def _export_log_entries(db: AsyncSession) -> AsyncIterator[list[str]]:
    rows = (
        await db.execute(
            select(LogEntry, LogEntryType.key, Unit.unit_code, Item.sku, Unit.item_id)
            .join(LogEntryType, LogEntryType.id == LogEntry.log_entry_type_id)
            .outerjoin(Unit, Unit.id == LogEntry.unit_id)
            .outerjoin(Item, Item.id == func.coalesce(LogEntry.item_id, Unit.item_id))
            .where(Unit.deleted_at.is_(None), Item.deleted_at.is_(None))
            .order_by(LogEntry.id)
        )
    ).all()
    keys = _attr_keys([r[0].values for r in rows], "value")
    yield ["id", "log_type", "unit_code", "item_sku", "performed_at", "notes", *keys]
    for entry, type_key, unit_code, sku, _ in rows:
        yield [
            str(entry.id),
            type_key,
            unit_code or "",
            sku or "",
            entry.performed_at.isoformat(),
            entry.notes or "",
            *(cell(entry.values.get(k.removeprefix("value."))) for k in keys),
        ]


_EXPORTERS = {
    "items": _export_items,
    "units": _export_units,
    "locations": _export_locations,
    "stock": _export_stock,
    "log_entries": _export_log_entries,
}


async def export_csv(db: AsyncSession, entity: Entity) -> AsyncIterator[str]:
    """UTF-8 CSV (with BOM, so Excel opens it correctly) of live (non-trashed) rows."""
    first = True
    async for row in _EXPORTERS[entity](db):
        yield (BOM if first else "") + _line(row)
        first = False


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


async def _dump(db: AsyncSession, model: Any, skip: Sequence[str] = ()) -> list[dict[str, Any]]:
    columns = [c.key for c in inspect(model).mapper.column_attrs if c.key not in skip]
    query = select(model).order_by(model.id)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    return [{c: _plain(getattr(row, c)) for c in columns} for row in await db.scalars(query)]


async def export_full_json(db: AsyncSession) -> dict[str, Any]:
    """Everything needed to rebuild an installation. Never includes `app_user`."""
    derived = ("search_text", "search_vector")
    fields = await _dump(db, FieldDefinition)
    log_types = await _dump(db, LogEntryType)
    categories = await _dump(db, Category)
    for category in categories:
        category["fields"] = [f for f in fields if f["category_id"] == category["id"]]
        category["log_entry_types"] = [t for t in log_types if t["category_id"] == category["id"]]
    items = await _dump(db, Item, derived)
    live_items = {i["id"] for i in items}
    locations = await _dump(db, Location)
    live_locs = {x["id"] for x in locations}
    for loc in locations:
        if loc["parent_id"] not in live_locs:
            loc["parent_id"] = None
    for item in items:
        if item["default_location_id"] not in live_locs:
            item["default_location_id"] = None
    units = [u for u in await _dump(db, Unit) if u["item_id"] in live_items]
    live_units = {u["id"] for u in units}
    for unit in units:
        if unit["location_id"] not in live_locs:
            unit["location_id"] = None
    targets = {"item": live_items, "unit": live_units, "location": live_locs}
    movements = [
        m
        for m in await _dump(db, StockMovement)
        if (m["item_id"] is None or m["item_id"] in live_items)
        and (m["unit_id"] is None or m["unit_id"] in live_units)
    ]
    live_moves = {m["id"] for m in movements}
    for move in movements:
        for col in ("from_location_id", "to_location_id"):
            if move[col] not in live_locs:
                move[col] = None
        if move["reverses_movement_id"] not in live_moves:
            move["reverses_movement_id"] = None
    log_entries = [
        e
        for e in await _dump(db, LogEntry)
        if (e["item_id"] in live_items) or (e["unit_id"] in live_units)
    ]
    live_logs = {e["id"] for e in log_entries}
    owners = {**targets, "log_entry": live_logs, "category": {c["id"] for c in categories}}
    return {
        "format": "pick2light-full-export",
        "version": 1,
        "exported_at": datetime.now().astimezone().isoformat(),
        "settings": await _dump(db, Setting),
        "categories": categories,
        "category_sequences": [
            {"category_id": s.category_id, "kind": s.kind, "next_value": s.next_value}
            for s in await db.scalars(select(CategorySequence))
        ],
        "location_types": await _dump(db, LocationType),
        "locations": locations,
        "items": items,
        "units": units,
        "stock": [
            r
            for r in await _dump(db, Stock)
            if r["item_id"] in live_items and r["location_id"] in live_locs
        ],
        "barcodes": [
            b for b in await _dump(db, Barcode) if b["target_id"] in targets[b["target_type"]]
        ],
        "stock_movements": movements,
        "log_entries": log_entries,
        "purchase_sources": [
            p for p in await _dump(db, PurchaseSource) if p["item_id"] in live_items
        ],
        "attachments": [
            a for a in await _dump(db, Attachment) if a["owner_id"] in owners[a["owner_type"]]
        ],
    }


# --------------------------------------------------------------------------- reading


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _sniff(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    best, best_count = ",", 0
    for delimiter in (",", ";", "\t"):
        count = len(next(csv.reader([first], delimiter=delimiter), []))
        if count > best_count:
            best, best_count = delimiter, count
    return best


def read_csv_lines(data: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Like `read_csv`, but each row carries the line of the file it starts on (header = 1)."""
    text = _decode(data)
    table: list[tuple[int, list[str]]] = []
    previous_end = 0
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=_sniff(text))
        for row in reader:
            start, previous_end = previous_end + 1, reader.line_num
            cells = [c.strip() for c in row]
            if any(cells):
                table.append((start, cells))
    except csv.Error as exc:
        raise ValidationFailed({"file": f"Cannot read the CSV: {exc}"}) from None
    if not table:
        return [], []
    headers = table[0][1]
    rows = [
        (line, {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)})
        for line, row in table[1:]
    ]
    return headers, rows


def read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows; blank rows dropped, cells stripped. Rows are numbered from 1."""
    headers, rows = read_csv_lines(data)
    return headers, [row for _, row in rows]


# --------------------------------------------------------------------------- import models

TARGETS = (
    "name", "sku", "description", "notes", "min_stock", "quantity", "location_code",
    "barcode", "unit_code", "serial_number", "condition", "ignore",
)  # fmt: skip
Action = Literal["create", "update", "add_stock", "create_unit", "skip"]


class ImportOptions(BaseModel):
    category_id: int
    mapping: dict[str, str]
    update_existing: bool = False
    skip_invalid: bool = False
    default_location_id: int | None = None


class RowResult(BaseModel):
    row: int  # 1-based among data rows
    line: int  # line of the file the row starts on (header is line 1)
    action: Action
    errors: dict[str, str] = {}
    values: dict[str, str] = {}


class ImportPreview(BaseModel):
    headers: list[str]
    rows: list[RowResult]
    counts: dict[str, int]


class _Ctx(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    opts: ImportOptions
    unit_mode: bool
    specs: list[FieldSpec]
    default_location_id: int | None


def _coerce(spec: FieldSpec, text: str) -> Any:
    """CSV cell to the value form `validate_values` expects (it parses SI numbers itself)."""
    if spec.type == "boolean":
        lowered = text.lower()
        if lowered in ("true", "yes", "y", "1"):
            return True
        if lowered in ("false", "no", "n", "0"):
            return False
        return text
    if spec.type == "multi_select":
        return [p.strip() for p in text.split(LIST_SEP) if p.strip()]
    if spec.type == "file" and text.isdigit():
        return int(text)
    return text


async def _check_mapping(db: AsyncSession, opts: ImportOptions, headers: list[str]) -> _Ctx:
    await get_category(db, opts.category_id)
    specs = await effective_fields(db, opts.category_id)
    keys = {s.key for s in specs}
    errors: dict[str, str] = {}
    seen: dict[str, str] = {}
    for header, target in opts.mapping.items():
        if header not in headers:
            errors[header] = "column not found in the file"
        elif target == "ignore":
            continue
        elif target.startswith("attr."):
            if target.removeprefix("attr.") not in keys:
                errors[header] = f"unknown field {target!r}"
        elif target not in TARGETS:
            errors[header] = f"unknown target {target!r}"
        if target != "ignore" and target in seen:
            errors[header] = f"{target!r} is already mapped from column {seen[target]!r}"
        seen[target] = header
    if errors:
        raise ValidationFailed(errors)
    if opts.default_location_id is not None:
        try:
            await get_location(db, opts.default_location_id)
        except NotFound:
            raise ValidationFailed({"default_location_id": "Location not found"}) from None
    return _Ctx(
        opts=opts,
        unit_mode=await effective_tracking_mode(db, opts.category_id) == "unit",
        specs=specs,
        default_location_id=opts.default_location_id,
    )


# --------------------------------------------------------------------------- row processing


async def _find_location(db: AsyncSession, code: str) -> int | None:
    return await db.scalar(
        select(Location.id).where(
            func.lower(Location.code) == code.lower(), Location.deleted_at.is_(None)
        )
    )


async def _find_item(
    db: AsyncSession, ctx: _Ctx, sku: str, name: str, errors: dict[str, str]
) -> Item | None:
    if sku:
        code = sanitize_code(sku).upper()
        found = await db.scalar(select(Item).where(Item.sku == code))
        if found is not None:
            if found.deleted_at is not None:
                errors["sku"] = "belongs to an item in the trash"
            elif found.category_id != ctx.opts.category_id:
                errors["sku"] = "already used by an item in another category"
            else:
                return found
            return None
    if name:
        return await db.scalar(
            select(Item)
            .where(
                Item.category_id == ctx.opts.category_id,
                Item.name == name,
                Item.deleted_at.is_(None),
            )
            .order_by(Item.id)
            .limit(1)
        )
    return None


def _split_attrs(ctx: _Ctx, values: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_key = {s.key: s for s in ctx.specs}
    item_attrs: dict[str, Any] = {}
    unit_attrs: dict[str, Any] = {}
    for target, text in values.items():
        if not target.startswith("attr."):
            continue
        key = target.removeprefix("attr.")
        spec = by_key[key]
        (unit_attrs if spec.scope == "unit" else item_attrs)[key] = _coerce(spec, text)
    return item_attrs, unit_attrs


def _validate_attrs(
    ctx: _Ctx,
    raw: dict[str, Any],
    scope: str,
    errors: dict[str, str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return validate_values(ctx.specs, raw, existing=existing, scope=scope)
    except ValidationFailed as exc:
        for key, message in (exc.fields or {}).items():
            errors[f"attr.{key}"] = message
        return {}


class _Plan(BaseModel):
    action: Action
    item_id: int | None = None
    values: dict[str, str]
    item_attrs: dict[str, Any] = {}
    unit_attrs: dict[str, Any] = {}
    quantity: Decimal | None = None
    location_id: int | None = None
    min_stock: int | None = None


async def _plan_row(
    db: AsyncSession, ctx: _Ctx, values: dict[str, str], errors: dict[str, str]
) -> _Plan:
    """Read-only checks for one row; fills `errors` and decides the action."""
    sku, name = values.get("sku", ""), values.get("name", "")
    if sku and not sanitize_code(sku):
        errors["sku"] = "must contain letters, digits, '.', '_' or '-'"
    item = await _find_item(db, ctx, sku, name, errors) if "sku" not in errors else None
    if item is None and not name and "sku" not in errors:
        errors["name"] = "required to create a new item"

    min_stock: int | None = None
    if values.get("min_stock"):
        try:
            min_stock = int(values["min_stock"])
            if min_stock < 0:
                raise ValueError
        except ValueError:
            errors["min_stock"] = "must be a whole number, 0 or more"

    quantity: Decimal | None = None
    if values.get("quantity") and not ctx.unit_mode:
        try:
            quantity = Decimal(values["quantity"])
            if not quantity.is_finite() or quantity < 0:
                raise DecimalError
        except DecimalError:
            errors["quantity"] = "must be a number, 0 or more"
            quantity = None
        if quantity == 0:
            quantity = None

    location_id: int | None = None
    if values.get("location_code"):
        location_id = await _find_location(db, values["location_code"])
        if location_id is None:
            errors["location_code"] = f"unknown location {values['location_code']!r}"
    elif ctx.default_location_id is not None:
        location_id = ctx.default_location_id
    elif item is not None and item.default_location_id is not None:
        location_id = item.default_location_id
    if quantity is not None and location_id is None and "location_code" not in errors:
        errors["location_code"] = "required when a quantity is given"

    condition = values.get("condition")
    if condition and condition not in UNIT_CONDITIONS:
        errors["condition"] = f"must be one of {', '.join(UNIT_CONDITIONS)}"
    unit_code = values.get("unit_code")
    if unit_code and ctx.unit_mode:
        code = sanitize_code(unit_code).upper()
        if not code:
            errors["unit_code"] = "must contain letters, digits, '.', '_' or '-'"
        elif await unit_code_taken(db, code):
            errors["unit_code"] = f"{code!r} is already in use"

    item_attrs, unit_attrs = _split_attrs(ctx, values)
    update = item is not None and ctx.opts.update_existing
    if item is None or (update and item_attrs):
        existing = item.attrs if item is not None else None
        item_attrs = _validate_attrs(ctx, item_attrs, "item", errors, existing)
    else:
        item_attrs = {}
    if ctx.unit_mode:
        unit_attrs = _validate_attrs(ctx, unit_attrs, "unit", errors)
    elif unit_attrs:
        _validate_attrs(ctx, unit_attrs, "item", errors)  # reports the unit-scope keys

    if ctx.unit_mode:
        action: Action = "create_unit"
    elif item is None:
        action = "create"
    elif quantity is not None:
        action = "add_stock"
    elif update:
        action = "update"
    else:
        action = "skip"
    return _Plan(
        action=action if not errors else "skip",
        item_id=item.id if item is not None else None,
        values=values,
        item_attrs=item_attrs,
        unit_attrs=unit_attrs,
        quantity=quantity,
        location_id=location_id,
        min_stock=min_stock,
    )


async def _write_row(db: AsyncSession, ctx: _Ctx, plan: _Plan) -> None:
    values = plan.values
    update = plan.item_id is not None and ctx.opts.update_existing
    if plan.item_id is None:
        item = await create_item(
            db,
            ItemIn(
                category_id=ctx.opts.category_id,
                name=values["name"],
                sku=values.get("sku") or None,
                description=values.get("description") or None,
                notes=values.get("notes") or None,
                attrs=plan.item_attrs,
                min_stock=plan.min_stock,
            ),
        )
    else:
        existing_item = await db.get(Item, plan.item_id)
        assert existing_item is not None
        item = existing_item
        if update:
            changes: dict[str, Any] = {}
            for field in ("name", "description", "notes"):
                if values.get(field):
                    changes[field] = values[field]
            if plan.min_stock is not None:
                changes["min_stock"] = plan.min_stock
            if plan.item_attrs:
                changes["attrs"] = plan.item_attrs
            if changes:
                item = await update_item(db, existing_item.id, ItemPatch(**changes))
    barcode = values.get("barcode")
    if ctx.unit_mode:
        unit = await create_unit(
            db,
            UnitIn(
                item_id=item.id,
                unit_code=values.get("unit_code") or None,
                serial_number=values.get("serial_number") or None,
                location_id=plan.location_id,
                condition=values.get("condition") or "untested",
                attrs=plan.unit_attrs,
            ),
            reason="import",
            source="import",
        )
        if barcode:
            await register_barcode(db, barcode, "unit", unit.id, "manufacturer")
    else:
        if barcode:
            await register_barcode(db, barcode, "item", item.id, "manufacturer")
        if plan.quantity is not None and plan.location_id is not None:
            await add_stock(
                db, item.id, plan.location_id, plan.quantity, reason="import", source="import"
            )


def _count(rows: list[RowResult]) -> dict[str, int]:
    counts = {a: 0 for a in ("create", "update", "add_stock", "create_unit", "skip")}
    for r in rows:
        counts[r.action] += 1
    counts["errors"] = sum(1 for r in rows if r.errors)
    return counts


async def _run(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    """Process every row, each in its own SAVEPOINT; writes stay in the caller's savepoint."""
    headers, table = read_csv_lines(data)
    ctx = await _check_mapping(db, opts, headers)
    results: list[RowResult] = []
    for number, (line, raw) in enumerate(table, start=1):
        values = {
            target: raw[header]
            for header, target in opts.mapping.items()
            if target != "ignore" and raw.get(header)
        }
        errors: dict[str, str] = {}
        plan = await _plan_row(db, ctx, values, errors)
        if not errors:
            savepoint = await db.begin_nested()
            try:
                await _write_row(db, ctx, plan)
                await savepoint.commit()
            except AppError as exc:
                await savepoint.rollback()
                errors.update(exc.fields or {"row": exc.message})
            except DBAPIError as exc:
                await savepoint.rollback()
                logger.warning("CSV import row %d failed: %s", number, exc.orig)
                errors["row"] = "Could not save this row"
        results.append(
            RowResult(
                row=number,
                line=line,
                action="skip" if errors else plan.action,
                errors=errors,
                values=values,
            )
        )
    return ImportPreview(headers=headers, rows=results, counts=_count(results))


async def preview_import(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    """Run the import for real inside a savepoint and roll it back: no writes remain."""
    outer = await db.begin_nested()
    try:
        return await _run(db, data, opts)
    finally:
        await outer.rollback()


async def apply_import(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    outer = await db.begin_nested()
    try:
        result = await _run(db, data, opts)
        bad = result.counts["errors"]
        if bad and not opts.skip_invalid:
            raise ValidationFailed({"rows": f"{bad} rows have errors"})
    except BaseException:
        await outer.rollback()
        raise
    await outer.commit()
    return result
