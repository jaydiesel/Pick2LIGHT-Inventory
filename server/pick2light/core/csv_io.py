"""CSV export/import and full JSON export (spec §9.2 CSV row)."""

import csv
import io
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light import __version__
from pick2light.core import categories as cats
from pick2light.core import stock
from pick2light.core.barcodes import register_barcode
from pick2light.core.fields import FieldSpec
from pick2light.core.items import ItemIn, ItemPatch, create_item, update_item
from pick2light.core.units import UnitIn, create_unit
from pick2light.errors import AppError, NotFound, ValidationFailed
from pick2light.models import (
    Attachment,
    Category,
    FieldDefinition,
    Item,
    Location,
    LocationType,
    LogEntry,
    LogEntryType,
    PurchaseSource,
    Stock,
    Unit,
)

Entity = Literal["items", "units", "locations", "stock", "log_entries"]
ENTITIES = ("items", "units", "locations", "stock", "log_entries")
BASE_TARGETS = {
    "name",
    "sku",
    "description",
    "notes",
    "min_stock",
    "quantity",
    "location_code",
    "barcode",
    "unit_code",
    "serial_number",
    "condition",
    "ignore",
}
CONDITIONS = {"new", "tested_good", "untested", "faulty", "for_parts"}


# ---------------------------------------------------------------- export


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = format(Decimal(repr(value)), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, list):
        return "|".join(_cell(v) for v in value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


async def _paths(db: AsyncSession, model: Any) -> dict[int, list[Any]]:
    rows = {r.id: r for r in await db.scalars(select(model))}
    out: dict[int, list[Any]] = {}
    for rid in rows:
        chain, cur, seen = [], rid, set()
        while cur is not None and cur in rows and cur not in seen:
            seen.add(cur)
            chain.append(rows[cur])
            cur = rows[cur].parent_id
        out[rid] = list(reversed(chain))
    return out


def _render(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return buf.getvalue()


async def export_csv(db: AsyncSession, entity: str) -> AsyncIterator[str]:
    if entity not in ENTITIES:
        raise NotFound(f"Unknown export '{entity}'")
    cat_paths = await _paths(db, Category)
    loc_paths = await _paths(db, Location)
    loc_code = {lid: chain[-1].code for lid, chain in loc_paths.items()}
    yield "﻿"
    if entity == "items":
        items = list(await db.scalars(select(Item).where(Item.deleted_at.is_(None)).order_by(Item.id)))
        keys = sorted({k for i in items for k in (i.attrs or {})})
        header = ["id", "sku", "name", "category_path", "description", "notes", "min_stock"]
        header += ["default_location_code", "on_hand", *[f"attr.{k}" for k in keys]]
        rows = [
            [
                i.id,
                i.sku,
                i.name,
                " / ".join(c.name for c in cat_paths.get(i.category_id, [])),
                i.description,
                i.notes,
                i.min_stock,
                loc_code.get(i.default_location_id) if i.default_location_id else None,
                await stock.on_hand(db, i.id),
                *[(i.attrs or {}).get(k) for k in keys],
            ]
            for i in items
        ]
        yield _render(header, rows)
    elif entity == "units":
        units = list(await db.scalars(select(Unit).where(Unit.deleted_at.is_(None)).order_by(Unit.id)))
        skus = {i.id: i.sku for i in await db.scalars(select(Item))}
        keys = sorted({k for u in units for k in (u.attrs or {})})
        header = ["id", "unit_code", "item_sku", "serial_number", "location_code", "condition", "status"]
        header += [f"attr.{k}" for k in keys]
        rows = [
            [
                u.id,
                u.unit_code,
                skus.get(u.item_id),
                u.serial_number,
                loc_code.get(u.location_id) if u.location_id else None,
                u.condition,
                u.status,
                *[(u.attrs or {}).get(k) for k in keys],
            ]
            for u in units
        ]
        yield _render(header, rows)
    elif entity == "locations":
        types = {t.id: t.name for t in await db.scalars(select(LocationType))}
        locs = list(
            await db.scalars(select(Location).where(Location.deleted_at.is_(None)).order_by(Location.id))
        )
        rows = [
            [
                loc.id,
                loc.code,
                loc.name,
                " / ".join(x.name for x in loc_paths[loc.id]),
                types.get(loc.location_type_id) if loc.location_type_id else None,
                loc_code.get(loc.parent_id) if loc.parent_id else None,
            ]
            for loc in locs
        ]
        yield _render(["id", "code", "name", "path", "type", "parent_code"], rows)
    elif entity == "stock":
        skus = {i.id: i.sku for i in await db.scalars(select(Item))}
        stocks = await db.scalars(
            select(Stock).where(Stock.quantity > 0).order_by(Stock.item_id, Stock.location_id)
        )
        rows = [[skus.get(s.item_id), loc_code.get(s.location_id), s.quantity] for s in stocks]
        yield _render(["item_sku", "location_code", "quantity"], rows)
    else:
        types_by_id = {t.id: t.key for t in await db.scalars(select(LogEntryType))}
        skus = {i.id: i.sku for i in await db.scalars(select(Item))}
        codes = {u.id: u.unit_code for u in await db.scalars(select(Unit))}
        entries = list(await db.scalars(select(LogEntry).order_by(LogEntry.performed_at, LogEntry.id)))
        keys = sorted({k for e in entries for k in (e.values or {})})
        header = [
            "id",
            "log_type",
            "unit_code",
            "item_sku",
            "performed_at",
            "notes",
            *[f"value.{k}" for k in keys],
        ]
        rows = [
            [
                e.id,
                types_by_id.get(e.log_entry_type_id),
                codes.get(e.unit_id) if e.unit_id else None,
                skus.get(e.item_id) if e.item_id else None,
                e.performed_at,
                e.notes,
                *[(e.values or {}).get(k) for k in keys],
            ]
            for e in entries
        ]
        yield _render(header, rows)


def _row_dict(obj: Any) -> dict[str, Any]:
    out = {}
    for attr in inspect(obj).mapper.column_attrs:
        if attr.key == "search_vector":
            continue
        value = getattr(obj, attr.key)
        out[attr.key] = value.isoformat() if isinstance(value, datetime | date) else value
    return out


async def export_full_json(db: AsyncSession) -> dict[str, Any]:
    async def rows(model: Any) -> list[dict[str, Any]]:
        return [_row_dict(r) for r in await db.scalars(select(model).order_by(model.id))]

    categories = await rows(Category)
    fields = await rows(FieldDefinition)
    log_types = await rows(LogEntryType)
    for c in categories:
        c["fields"] = [f for f in fields if f["category_id"] == c["id"]]
        c["log_types"] = [t for t in log_types if t["category_id"] == c["id"]]
    return {
        "version": __version__,
        "exported_at": datetime.now().astimezone().isoformat(),
        "categories": categories,
        "location_types": await rows(LocationType),
        "locations": await rows(Location),
        "items": await rows(Item),
        "units": await rows(Unit),
        "stock": await rows(Stock),
        "log_entries": await rows(LogEntry),
        "purchase_sources": await rows(PurchaseSource),
        "attachments": await rows(Attachment),
    }


# ---------------------------------------------------------------- import


class ImportOptions(BaseModel):
    category_id: int
    mapping: dict[str, str]
    update_existing: bool = False
    skip_invalid: bool = False
    default_location_id: int | None = None


class RowResult(BaseModel):
    row: int
    action: Literal["create", "update", "add_stock", "create_unit", "skip"]
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}


class ImportPreview(BaseModel):
    headers: list[str]
    rows: list[RowResult]
    counts: dict[str, int]


def read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max((",", ";", "\t"), key=first.count)  # header line decides; ties keep ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for raw in reader:
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        if not headers:
            headers = cells
            continue
        cells += [""] * (len(headers) - len(cells))
        rows.append(dict(zip(headers, cells, strict=False)))
    if not headers:
        raise ValidationFailed({"file": "The file is empty"})
    return headers, rows


def _cell_value(spec: FieldSpec, text: str) -> Any:
    """Turn a CSV cell into input for validate_values (labels → option values, yes/no → bool)."""
    if spec.type == "boolean":
        lowered = text.lower()
        if lowered in ("true", "yes", "y", "1", "x"):
            return True
        if lowered in ("false", "no", "n", "0"):
            return False
        return text
    if spec.type in ("select", "multi_select"):
        parts = [p.strip() for p in text.split("|")] if spec.type == "multi_select" else [text]
        mapped = []
        for p in parts:
            match = next(
                (
                    o["value"]
                    for o in spec.options
                    if p.lower() in (o["value"].lower(), (o.get("label") or "").lower())
                ),
                p,
            )
            mapped.append(match)
        return mapped if spec.type == "multi_select" else mapped[0]
    if spec.type == "file":
        return int(text) if text.isdigit() else text
    return text


class _Ctx:
    def __init__(self, opts: ImportOptions, mode: str, specs: list[FieldSpec], locations: dict[str, int]):
        self.opts = opts
        self.mode = mode
        self.specs = {s.key: s for s in specs}
        self.locations = locations
        self.column_for = {target: col for col, target in opts.mapping.items()}

    def col(self, target: str) -> str:
        return self.column_for.get(target, target)


async def _location_codes(db: AsyncSession) -> dict[str, int]:
    rows = await db.scalars(select(Location).where(Location.deleted_at.is_(None)))
    out: dict[str, int] = {}
    for loc in rows:
        out[loc.code] = loc.id
        out.setdefault(loc.code.lower(), loc.id)
    return out


def _parse_row(
    ctx: _Ctx, row: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """Return (base values, item attrs, unit attrs, errors keyed by column)."""
    base: dict[str, Any] = {}
    item_attrs: dict[str, Any] = {}
    unit_attrs: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for column, target in ctx.opts.mapping.items():
        text = (row.get(column) or "").strip()
        if target == "ignore" or not text:
            continue
        if target.startswith("attr."):
            key = target[5:]
            spec = ctx.specs.get(key)
            if spec is None:
                errors[column] = f"No field '{key}' in this category"
                continue
            (unit_attrs if spec.scope == "unit" else item_attrs)[key] = _cell_value(spec, text)
        elif target in ("quantity", "min_stock"):
            try:
                number = float(text)
            except ValueError:
                errors[column] = "Must be a number"
                continue
            if number < 0:
                errors[column] = "Can't be negative"
                continue
            base[target] = int(number) if target == "min_stock" else number
        elif target == "location_code":
            loc_id = ctx.locations.get(text) or ctx.locations.get(text.lower())
            if loc_id is None:
                errors[column] = f"Unknown location code '{text}'"
            else:
                base["location_id"] = loc_id
                base[target] = text
        elif target == "condition":
            value = text.lower().replace(" ", "_")
            if value not in CONDITIONS:
                errors[column] = f"Must be one of: {', '.join(sorted(CONDITIONS))}"
            else:
                base[target] = value
        elif target in BASE_TARGETS:
            base[target] = text
        else:
            errors[column] = f"Unknown target '{target}'"
    return base, item_attrs, unit_attrs, errors


def _map_errors(ctx: _Ctx, fields: dict[str, str]) -> dict[str, str]:
    out = {}
    for key, msg in fields.items():
        target = key if key in BASE_TARGETS else f"attr.{key}"
        if key == "default_location_id":
            target = "location_code"
        out[ctx.col(target)] = msg
    return out


async def _find_item(db: AsyncSession, ctx: _Ctx, base: dict[str, Any]) -> Item | None:
    if base.get("sku"):
        item = await db.scalar(select(Item).where(Item.sku == base["sku"], Item.deleted_at.is_(None)))
        if item is not None:
            if item.category_id != ctx.opts.category_id:
                raise ValidationFailed({"sku": "This SKU belongs to an item in another category"})
            return item
    if base.get("name"):
        return await db.scalar(
            select(Item).where(
                Item.category_id == ctx.opts.category_id, Item.name == base["name"], Item.deleted_at.is_(None)
            )
        )
    return None


async def _process_row(db: AsyncSession, ctx: _Ctx, row: dict[str, str], number: int) -> RowResult:
    base, item_attrs, unit_attrs, errors = _parse_row(ctx, row)
    values = {k: v for k, v in base.items() if k != "location_id"}
    if errors:
        return RowResult(row=number, action="skip", errors=errors, values=values)
    try:
        async with db.begin_nested():
            item = await _find_item(db, ctx, base)
            action: str
            if item is None:
                if not base.get("name"):
                    raise ValidationFailed({"name": "Required for new items"})
                default_loc = (
                    None if ctx.mode == "unit" else (base.get("location_id") or ctx.opts.default_location_id)
                )
                item = await create_item(
                    db,
                    ItemIn(
                        category_id=ctx.opts.category_id,
                        name=base["name"],
                        sku=base.get("sku"),
                        description=base.get("description"),
                        notes=base.get("notes"),
                        attrs=item_attrs,
                        min_stock=base.get("min_stock"),
                        default_location_id=default_loc,
                    ),
                )
                action = "create"
            else:
                action = "skip"
                if ctx.opts.update_existing:
                    patch = {k: base[k] for k in ("description", "notes", "min_stock") if k in base}
                    await update_item(db, item.id, ItemPatch(attrs=item_attrs or None, **patch))
                    action = "update"
            if base.get("barcode"):
                await register_barcode(db, base["barcode"], "item", item.id, "manufacturer")
            if ctx.mode == "unit":
                unit = await create_unit(
                    db,
                    UnitIn(
                        item_id=item.id,
                        unit_code=base.get("unit_code"),
                        serial_number=base.get("serial_number"),
                        location_id=base.get("location_id") or ctx.opts.default_location_id,
                        condition=base.get("condition", "untested"),
                        attrs=unit_attrs,
                    ),
                    reason="import",
                    source="import",
                )
                values["unit_code"] = unit.unit_code
                action = "create_unit"
            elif base.get("quantity"):
                loc_id = base.get("location_id") or ctx.opts.default_location_id or item.default_location_id
                if loc_id is None:
                    raise ValidationFailed({"location_code": "Needed for the quantity"})
                await stock.add_stock(db, item.id, loc_id, base["quantity"], reason="import", source="import")
                if action == "skip":
                    action = "add_stock"
            values.update(
                {
                    f"attr.{k}": v
                    for k, v in {**item.attrs, **unit_attrs}.items()
                    if f"attr.{k}" in ctx.column_for
                }
            )
            values["sku"] = item.sku
    except ValidationFailed as exc:
        return RowResult(row=number, action="skip", errors=_map_errors(ctx, exc.fields), values=values)
    except AppError as exc:
        return RowResult(row=number, action="skip", errors={"row": exc.message}, values=values)
    return RowResult(row=number, action=action, values=values)  # type: ignore[arg-type]


async def _run(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    await cats.get_category(db, opts.category_id)
    headers, rows = read_csv(data)
    missing = [c for c in opts.mapping if c not in headers]
    if missing:
        raise ValidationFailed({"mapping": f"Column not in file: {missing[0]}"})
    mode = await cats.effective_tracking_mode(db, opts.category_id)
    ctx = _Ctx(opts, mode, await cats.effective_fields(db, opts.category_id), await _location_codes(db))
    results = [await _process_row(db, ctx, row, i) for i, row in enumerate(rows, start=1)]
    counts: dict[str, int] = {}
    for r in results:
        if not r.errors:
            counts[r.action] = counts.get(r.action, 0) + 1
    counts["errors"] = sum(1 for r in results if r.errors)
    return ImportPreview(headers=headers, rows=results, counts=counts)


async def preview_import(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    savepoint = await db.begin_nested()
    try:
        return await _run(db, data, opts)
    finally:
        await savepoint.rollback()


async def apply_import(db: AsyncSession, data: bytes, opts: ImportOptions) -> ImportPreview:
    preview = await preview_import(db, data, opts)
    bad = preview.counts.get("errors", 0)
    if bad and not opts.skip_invalid:
        raise ValidationFailed({"rows": f"{bad} row has errors" if bad == 1 else f"{bad} rows have errors"})
    return await _run(db, data, opts)
