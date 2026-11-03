import csv
import io
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, func, select

from pick2light.core.barcodes import register_barcode
from pick2light.core.categories import LogEntryTypeIn, create_log_type
from pick2light.core.csv_io import (
    ImportOptions,
    apply_import,
    export_csv,
    export_full_json,
    preview_import,
    read_csv,
)
from pick2light.core.logs import LogEntryIn, add_log_entry
from pick2light.errors import ValidationFailed
from pick2light.models import Barcode, Item, Stock, StockMovement, Unit
from tests.factories import make_category, make_item, make_location, make_unit

FIXTURES = Path(__file__).parent / "fixtures"
RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}
KIND = {
    "key": "kind",
    "type": "select",
    "options": [{"value": "film", "label": "Film"}, {"value": "wire", "label": "Wire"}],
}
TAGS = {
    "key": "tags",
    "type": "multi_select",
    "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
}
SMD = {"key": "smd", "type": "boolean"}


async def _collect(db, entity) -> str:
    return "".join([chunk async for chunk in export_csv(db, entity)])


def _parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


async def _resistors(db):
    return await make_category(
        db, "Resistors", sku_prefix="R", fields=[RESISTANCE, KIND, TAGS, SMD]
    )


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


async def test_export_items_has_attr_columns_and_bom(db):
    cat = await _resistors(db)
    loc = await make_location(db, "Shelf")
    await make_item(
        db,
        cat,
        "10k",
        attrs={"resistance": "10k", "kind": "film", "tags": ["a", "b"], "smd": True},
    )
    await make_item(db, cat, "Plain")
    text = await _collect(db, "items")
    assert text.startswith("﻿")
    rows = _parse(text)
    header = list(rows[0])
    assert header[:9] == [
        "id", "sku", "name", "category_path", "description", "notes",
        "min_stock", "default_location_code", "on_hand",
    ]  # fmt: skip
    assert header[9:] == ["attr.kind", "attr.resistance", "attr.smd", "attr.tags"]
    first = rows[0]
    assert first["category_path"] == "Resistors"
    assert first["attr.resistance"] == "10000"
    assert first["attr.tags"] == "a|b"
    assert first["attr.smd"] == "true"
    assert first["attr.kind"] == "film"
    assert rows[1]["attr.resistance"] == ""
    assert loc.code  # location created; unused here


async def test_export_excludes_trashed(db):
    from pick2light.core.items import delete_item

    cat = await _resistors(db)
    keep = await make_item(db, cat, "Keep")
    gone = await make_item(db, cat, "Gone")
    await delete_item(db, gone.id)
    rows = _parse(await _collect(db, "items"))
    assert [r["sku"] for r in rows] == [keep.sku]


async def test_export_other_entities(db):
    from pick2light.core.stock import add_stock

    room = await make_location(db, "Room")
    shelf = await make_location(db, "Shelf", parent=room)
    cat = await _resistors(db)
    item = await make_item(db, cat, "Bulk")
    await add_stock(db, item.id, shelf.id, 7)
    cells = await make_category(db, "Cells", tracking_mode="unit")
    cell_item = await make_item(db, cells, "18650")
    unit = await make_unit(db, cell_item, location_id=shelf.id, serial_number="SN1")
    log_type = await create_log_type(
        db,
        cells.id,
        LogEntryTypeIn.model_validate(
            {
                "key": "cap",
                "name": "Capacity",
                "applies_to": "unit",
                "fields": [{"key": "mah", "label": "mAh", "type": "number"}],
            }
        ),
    )
    await add_log_entry(
        db, LogEntryIn(log_entry_type_id=log_type.id, unit_id=unit.id, values={"mah": 2500})
    )

    locs = _parse(await _collect(db, "locations"))
    assert [r["path"] for r in locs] == ["Room", "Room / Shelf"]
    assert locs[1]["parent_code"] == room.code
    stock = _parse(await _collect(db, "stock"))
    assert stock == [{"item_sku": item.sku, "location_code": shelf.code, "quantity": "7"}]
    units = _parse(await _collect(db, "units"))
    assert units[0]["unit_code"] == unit.unit_code
    assert units[0]["item_sku"] == cell_item.sku
    assert units[0]["location_code"] == shelf.code
    assert units[0]["serial_number"] == "SN1"
    logs = _parse(await _collect(db, "log_entries"))
    assert logs[0]["log_type"] == "cap"
    assert logs[0]["unit_code"] == unit.unit_code
    assert logs[0]["value.mah"] == "2500"


async def test_export_roundtrip_items(db):
    cat = await _resistors(db)
    await make_item(
        db, cat, "10k", attrs={"resistance": "10k", "kind": "film", "tags": ["a", "b"], "smd": True}
    )
    await make_item(db, cat, "4u7", attrs={"resistance": 0.0000047, "smd": False}, notes="n")
    before = {i.sku: (i.name, i.attrs, i.notes) for i in await db.scalars(select(Item))}
    text = await _collect(db, "items")
    # empty the system of those rows (hard delete) and import into a fresh category
    await db.execute(delete(Barcode))
    await db.execute(delete(Item))
    target = await _resistors(db)
    target_id = target.id
    headers, _ = read_csv(text.encode("utf-8"))
    mapping = {
        h: h
        for h in headers
        if h in ("sku", "name", "description", "notes") or h.startswith("attr.")
    }
    mapping.update({h: "ignore" for h in headers if h not in mapping})
    result = await apply_import(
        db, text.encode("utf-8"), ImportOptions(category_id=target_id, mapping=mapping)
    )
    assert all(r.action == "create" and not r.errors for r in result.rows)
    after = {i.sku: (i.name, i.attrs, i.notes) for i in await db.scalars(select(Item))}
    assert after == before


async def test_preview_tolerates_bom_semicolon_blank_rows(db):
    cat = await _resistors(db)
    loc = await make_location(db, "Shelf", code="SHELF")
    data = (FIXTURES / "excel_semicolon.csv").read_bytes()
    headers, rows = read_csv(data)
    assert headers == ["Name", "SKU", "Resistance", "Qty", "Loc"]
    assert len(rows) == 2  # blank and ;;;; rows dropped
    assert rows[0]["Resistance"] == "4k7"
    mapping = {
        "Name": "name",
        "SKU": "sku",
        "Resistance": "attr.resistance",
        "Qty": "quantity",
        "Loc": "location_code",
    }
    preview = await preview_import(db, data, ImportOptions(category_id=cat.id, mapping=mapping))
    assert [r.row for r in preview.rows] == [1, 2]
    assert preview.rows[0].errors == {}
    assert preview.rows[0].action == "create"
    assert preview.rows[0].values["attr.resistance"] == "4k7"
    assert preview.counts["create"] == 2
    assert loc.code == "SHELF"


async def test_read_csv_cp1252_and_tab(db):
    data = "Name\tNote\nWiderstand\tgrößer\n".encode("cp1252")
    headers, rows = read_csv(data)
    assert headers == ["Name", "Note"]
    assert rows == [{"Name": "Widerstand", "Note": "größer"}]


async def test_apply_semicolon_fixture_writes_4700(db):
    cat = await _resistors(db)
    await make_location(db, "Shelf", code="SHELF")
    data = (FIXTURES / "excel_semicolon.csv").read_bytes()
    mapping = {
        "Name": "name",
        "Resistance": "attr.resistance",
        "Qty": "quantity",
        "Loc": "location_code",
        "SKU": "ignore",
    }
    await apply_import(db, data, ImportOptions(category_id=cat.id, mapping=mapping))
    item = await db.scalar(select(Item).where(Item.name == "10k resistor"))
    assert item.attrs == {"resistance": 4700}
    assert await db.scalar(select(func.sum(Stock.quantity))) == 7


async def test_preview_does_not_write(db):
    cat = await _resistors(db)
    cat_id = cat.id
    loc = await make_location(db, "Shelf")
    data = _csv("name,qty,loc", f"A,3,{loc.code}", f"B,1,{loc.code}")
    opts = ImportOptions(
        category_id=cat_id, mapping={"name": "name", "qty": "quantity", "loc": "location_code"}
    )
    preview = await preview_import(db, data, opts)
    assert preview.counts["create"] == 2
    assert await _count(db, Item) == 0
    assert await _count(db, Stock) == 0
    assert await _count(db, StockMovement) == 0
    assert await _count(db, Barcode) == 1  # only the location code
    # generated SKUs are not consumed by a preview
    applied = await apply_import(db, data, opts)
    assert [r.values["name"] for r in applied.rows] == ["A", "B"]
    skus = sorted(await db.scalars(select(Item.sku)))
    assert skus == ["R-0001", "R-0002"]


async def test_row_errors_reported_per_row(db):
    cat = await _resistors(db)
    data = _csv("name,kind", "A,film", "B,plastic", "C,wire")
    opts = ImportOptions(category_id=cat.id, mapping={"name": "name", "kind": "attr.kind"})
    preview = await preview_import(db, data, opts)
    assert [bool(r.errors) for r in preview.rows] == [False, True, False]
    assert "attr.kind" in preview.rows[1].errors
    assert preview.rows[1].action == "skip"
    assert preview.counts["errors"] == 1


async def test_apply_with_errors_refused_without_skip(db):
    cat = await _resistors(db)
    data = _csv("name,kind", "A,film", "B,plastic")
    opts = ImportOptions(category_id=cat.id, mapping={"name": "name", "kind": "attr.kind"})
    with pytest.raises(ValidationFailed) as exc:
        await apply_import(db, data, opts)
    assert exc.value.fields == {"rows": "1 rows have errors"}
    assert await _count(db, Item) == 0


async def test_apply_skip_invalid_applies_valid_rows(db):
    cat = await _resistors(db)
    data = _csv("name,kind", "A,film", "B,plastic", "C,wire")
    opts = ImportOptions(
        category_id=cat.id, mapping={"name": "name", "kind": "attr.kind"}, skip_invalid=True
    )
    result = await apply_import(db, data, opts)
    assert result.counts["create"] == 2
    names = sorted(await db.scalars(select(Item.name)))
    assert names == ["A", "C"]
    moves = await db.scalar(select(func.count()).select_from(StockMovement))
    assert moves == 0


async def test_existing_sku_adds_stock(db):
    cat = await _resistors(db)
    loc = await make_location(db, "Shelf")
    item = await make_item(db, cat, "Existing")
    item_id, sku = item.id, item.sku
    data = _csv("sku,name,qty", f"{sku},Renamed,4")
    mapping = {"sku": "sku", "name": "name", "qty": "quantity"}
    opts = ImportOptions(category_id=cat.id, mapping=mapping, default_location_id=loc.id)
    result = await apply_import(db, data, opts)
    assert result.rows[0].action == "add_stock"
    assert await _count(db, Item) == 1
    assert await db.scalar(select(Stock.quantity).where(Stock.item_id == item_id)) == 4
    move = await db.scalar(select(StockMovement))
    assert (move.reason, move.source) == ("import", "import")
    # name untouched without update_existing
    assert (await db.get(Item, item_id)).name == "Existing"
    opts2 = opts.model_copy(update={"update_existing": True})
    await apply_import(db, data, opts2)
    assert (await db.get(Item, item_id)).name == "Renamed"
    assert await db.scalar(select(Stock.quantity).where(Stock.item_id == item_id)) == 8


async def test_match_by_name_within_category(db):
    cat = await _resistors(db)
    loc = await make_location(db, "Shelf")
    await make_item(db, cat, "Same")
    data = _csv("name,qty", "Same,2")
    opts = ImportOptions(
        category_id=cat.id,
        mapping={"name": "name", "qty": "quantity"},
        default_location_id=loc.id,
    )
    result = await apply_import(db, data, opts)
    assert result.rows[0].action == "add_stock"
    assert await _count(db, Item) == 1


async def test_unknown_location_code_row_error(db):
    cat = await _resistors(db)
    data = _csv("name,qty,loc", "A,1,NOPE")
    opts = ImportOptions(
        category_id=cat.id,
        mapping={"name": "name", "qty": "quantity", "loc": "location_code"},
    )
    preview = await preview_import(db, data, opts)
    assert "location_code" in preview.rows[0].errors


async def test_quantity_without_location_is_error(db):
    cat = await _resistors(db)
    data = _csv("name,qty", "A,1")
    opts = ImportOptions(category_id=cat.id, mapping={"name": "name", "qty": "quantity"})
    preview = await preview_import(db, data, opts)
    assert "location_code" in preview.rows[0].errors


async def test_unit_category_rows_create_units(db):
    cells = await make_category(db, "Cells", tracking_mode="unit", unit_id_pattern="C{seq:4}")
    loc = await make_location(db, "Shelf")
    data = _csv(
        "name,serial,cond,loc,bc",
        f"18650,S1,new,{loc.code},BC1",
        f"18650,S2,faulty,{loc.code},",
        "18650,,,,",
    )
    mapping = {
        "name": "name",
        "serial": "serial_number",
        "cond": "condition",
        "loc": "location_code",
        "bc": "barcode",
    }
    result = await apply_import(db, data, ImportOptions(category_id=cells.id, mapping=mapping))
    assert [r.action for r in result.rows] == ["create_unit"] * 3
    assert await _count(db, Item) == 1
    units = list(await db.scalars(select(Unit).order_by(Unit.id)))
    assert [u.unit_code for u in units] == ["C0001", "C0002", "C0003"]
    assert [u.condition for u in units] == ["new", "faulty", "untested"]
    assert units[0].location_id is not None
    movement = await db.scalar(select(StockMovement).where(StockMovement.unit_id == units[0].id))
    assert (movement.reason, movement.source) == ("import", "import")
    bc = await db.scalar(select(Barcode).where(Barcode.code == "BC1"))
    assert (bc.kind, bc.target_type) == ("manufacturer", "unit")


async def test_unit_duplicate_code_is_row_error(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    data = _csv("name,code", f"18650,{unit.unit_code}")
    opts = ImportOptions(category_id=cells.id, mapping={"name": "name", "code": "unit_code"})
    preview = await preview_import(db, data, opts)
    assert "unit_code" in preview.rows[0].errors


async def test_full_json_export_contains_all_sections(db):
    cat = await _resistors(db)
    loc = await make_location(db, "Shelf")
    item = await make_item(db, cat, "A")
    from pick2light.core.stock import add_stock

    await add_stock(db, item.id, loc.id, 2)
    data = await export_full_json(db)
    for key in (
        "categories", "location_types", "locations", "items", "units", "stock",
        "log_entries", "purchase_sources", "attachments", "barcodes", "settings",
    ):  # fmt: skip
        assert key in data, key
    assert data["categories"][0]["fields"]
    assert "log_entry_types" in data["categories"][0]
    assert data["items"][0]["sku"] == item.sku
    assert float(data["stock"][0]["quantity"]) == 2
    json.dumps(data)  # serialisable


async def test_full_json_never_contains_credentials(db):
    from pick2light.core.auth import set_password

    await set_password(db, "admin", "correct horse")
    data = await export_full_json(db)
    text = json.dumps(data)

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    assert not [k for k in keys(data) if "password" in k.lower() or "hash" in k.lower()]
    assert "app_user" not in data
    assert "$argon2" not in text and "pbkdf2" not in text and "scrypt" not in text
    assert "admin" not in text


async def test_api_export_and_import(client: httpx.AsyncClient, db):
    cat = await _resistors(db)
    await make_item(db, cat, "10k", attrs={"resistance": "10k"})
    res = await client.get("/api/v1/export/items.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert "items.csv" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")
    full = await client.get("/api/v1/export/full.json")
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("application/json")
    assert "items" in full.json()

    options = json.dumps({"category_id": cat.id, "mapping": {"name": "name"}})
    files = {"file": ("in.csv", b"name\nNew one\n", "text/csv")}
    prev = await client.post("/api/v1/import/csv/preview", files=files, data={"options": options})
    assert prev.status_code == 200
    assert prev.json()["counts"]["create"] == 1
    applied = await client.post("/api/v1/import/csv/apply", files=files, data={"options": options})
    assert applied.status_code == 200
    assert await _count(db, Item) == 2
    bad = await client.post("/api/v1/import/csv/apply", files=files, data={"options": "{not json"})
    assert bad.status_code == 422


def _refs(data):
    """(section, column, parent section, row id) for every reference that points nowhere."""
    ids = {
        k: {r["id"] for r in v}
        for k, v in data.items()
        if isinstance(v, list) and v and "id" in v[0]
    }
    ids.setdefault("units", set())
    checks = [
        ("units", "item_id", "items"),
        ("stock", "item_id", "items"),
        ("stock", "location_id", "locations"),
        ("log_entries", "item_id", "items"),
        ("log_entries", "unit_id", "units"),
        ("stock_movements", "item_id", "items"),
        ("stock_movements", "unit_id", "units"),
        ("purchase_sources", "item_id", "items"),
    ]
    bad = []
    for section, col, parent in checks:
        for row in data[section]:
            if row[col] is not None and row[col] not in ids.get(parent, set()):
                bad.append((section, col, row[col]))
    for row in data["barcodes"]:
        parent = {"item": "items", "unit": "units", "location": "locations"}[row["target_type"]]
        if row["target_id"] not in ids.get(parent, set()):
            bad.append(("barcodes", row["code"], row["target_id"]))
    for row in data["attachments"]:
        parent = {"item": "items", "unit": "units", "location": "locations"}.get(row["owner_type"])
        if parent and row["owner_id"] not in ids.get(parent, set()):
            bad.append(("attachments", "owner_id", row["owner_id"]))
    return bad


async def test_full_json_has_no_dangling_references(db):
    from pick2light.core.items import delete_item
    from pick2light.core.locations import delete_location
    from pick2light.core.stock import add_stock, consume_unit, remove_stock
    from pick2light.core.units import delete_unit

    loc = await make_location(db, "Shelf")
    trashed_loc = await make_location(db, "Old")
    bulk = await _resistors(db)
    live = await make_item(db, bulk, "Live")
    gone = await make_item(db, bulk, "Gone")
    await add_stock(db, gone.id, loc.id, 2)
    await add_stock(db, live.id, trashed_loc.id, 1)
    await remove_stock(db, gone.id, loc.id, 2)
    await register_barcode(db, "GONE-BC", "item", gone.id, "manufacturer")
    cells = await make_category(db, "Cells", tracking_mode="unit")
    cell_item = await make_item(db, cells, "18650")
    unit = await make_unit(db, cell_item, location_id=loc.id)
    log_type = await create_log_type(
        db,
        cells.id,
        LogEntryTypeIn.model_validate({"key": "cap", "name": "Cap", "applies_to": "unit"}),
    )
    await add_log_entry(db, LogEntryIn(log_entry_type_id=log_type.id, unit_id=unit.id))
    other = await make_unit(db, cell_item, location_id=loc.id)
    await consume_unit(db, unit.id)
    await delete_unit(db, unit.id)
    await consume_unit(db, other.id)
    await delete_item(db, gone.id)
    await remove_stock(db, live.id, trashed_loc.id, 1)
    await delete_location(db, trashed_loc.id)
    await delete_unit(db, other.id)
    await delete_item(db, cell_item.id)

    data = await export_full_json(db)
    assert _refs(data) == []
    assert [i["sku"] for i in data["items"]] == [live.sku]
    assert data["units"] == [] and data["log_entries"] == []
    assert all(b["code"] != "GONE-BC" for b in data["barcodes"])
    assert data["stock_movements"]  # live item's movements remain


async def test_preview_reports_source_lines(db):
    cat = await _resistors(db)
    data = (FIXTURES / "excel_semicolon.csv").read_bytes()
    mapping = {"Name": "name", "SKU": "sku", "Resistance": "attr.resistance"}
    preview = await preview_import(db, data, ImportOptions(category_id=cat.id, mapping=mapping))
    assert [(r.row, r.line) for r in preview.rows] == [(1, 2), (2, 5)]


async def test_oversized_field_is_validation_error(db):
    big = b"name\n" + b"x" * (csv.field_size_limit() + 10) + b"\n"
    with pytest.raises(ValidationFailed) as exc:
        read_csv(big)
    assert "file" in exc.value.fields


async def test_write_failure_message_is_generic(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from pick2light.core import csv_io

    cat = await _resistors(db)

    async def boom(*a, **k):
        raise IntegrityError("INSERT secret_table", {}, Exception("duplicate key secret_table"))

    monkeypatch.setattr(csv_io, "create_item", boom)
    preview = await preview_import(
        db, b"name\nA\n", ImportOptions(category_id=cat.id, mapping={"name": "name"})
    )
    assert preview.rows[0].errors == {"row": "Could not save this row"}
