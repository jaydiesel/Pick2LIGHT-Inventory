import csv
import io
import json
from pathlib import Path

import pytest
from factories import RES_FIELDS, make_category, make_item, make_location, make_unit
from sqlalchemy import delete, select

from pick2light.core import csv_io, stock
from pick2light.core.csv_io import ImportOptions, apply_import, preview_import, read_csv
from pick2light.errors import ValidationFailed
from pick2light.models import Barcode, Item, StockMovement

FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = {
    "Name": "name",
    "Resistance": "attr.resistance",
    "Package": "attr.package",
    "Qty": "quantity",
    "Location": "location_code",
}


async def collect(it) -> str:
    return "".join([chunk async for chunk in it])


async def resistors(db):
    return await make_category(db, "Resistors", fields=RES_FIELDS)


def test_read_csv_semicolon_bom_blank_rows():
    headers, rows = read_csv((FIXTURES / "excel_semicolon.csv").read_bytes())
    assert headers == ["Name", "Resistance", "Package", "Qty", "Location"]
    assert len(rows) == 3
    assert rows[0]["Resistance"] == "4k7"


async def test_export_items_has_attr_columns_and_bom(db):
    cat = await resistors(db)
    await make_item(db, cat, "R", attrs={"resistance": 4700, "package": "0805"})
    text = await collect(csv_io.export_csv(db, "items"))
    assert text.startswith("﻿")
    header = next(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert header[:9] == [
        "id",
        "sku",
        "name",
        "category_path",
        "description",
        "notes",
        "min_stock",
        "default_location_code",
        "on_hand",
    ]
    assert header[9:] == ["attr.package", "attr.resistance"]


async def test_export_roundtrip_items(db):
    cat = await resistors(db)
    await make_item(db, cat, "R1", attrs={"resistance": 4700, "package": "0805"})
    await make_item(db, cat, "R2", attrs={"resistance": 10, "package": "0603"})
    data = (await collect(csv_io.export_csv(db, "items"))).encode()
    before = {i.sku: i.attrs for i in await db.scalars(select(Item))}
    await db.execute(delete(Barcode))
    await db.execute(delete(Item))
    mapping = {
        "sku": "sku",
        "name": "name",
        "attr.resistance": "attr.resistance",
        "attr.package": "attr.package",
    }
    await apply_import(db, data, ImportOptions(category_id=cat.id, mapping=mapping))
    after = {i.sku: i.attrs for i in await db.scalars(select(Item))}
    assert after == before


async def test_preview_tolerates_bom_semicolon_blank_rows(db):
    cat = await resistors(db)
    await make_location(db, "Drawer", code="A1")
    preview = await preview_import(
        db,
        (FIXTURES / "excel_semicolon.csv").read_bytes(),
        ImportOptions(category_id=cat.id, mapping=MAPPING),
    )
    assert [r.row for r in preview.rows] == [1, 2, 3]
    first = preview.rows[0]
    assert first.action == "create" and first.errors == {} and first.values["attr.resistance"] == 4700


async def test_preview_does_not_write(db):
    cat = await resistors(db)
    await make_location(db, "Drawer", code="A1")
    await preview_import(
        db,
        (FIXTURES / "excel_semicolon.csv").read_bytes(),
        ImportOptions(category_id=cat.id, mapping=MAPPING),
    )
    assert list(await db.scalars(select(Item))) == []


async def test_row_errors_reported_per_row(db):
    cat = await resistors(db)
    await make_location(db, "Drawer", code="A1")
    preview = await preview_import(
        db,
        (FIXTURES / "excel_semicolon.csv").read_bytes(),
        ImportOptions(category_id=cat.id, mapping=MAPPING),
    )
    assert [bool(r.errors) for r in preview.rows] == [False, True, False]
    assert "Package" in preview.rows[1].errors
    assert preview.counts == {"create": 2, "errors": 1}


async def test_apply_with_errors_refused_without_skip(db):
    cat = await resistors(db)
    await make_location(db, "Drawer", code="A1")
    with pytest.raises(ValidationFailed) as e:
        await apply_import(
            db,
            (FIXTURES / "excel_semicolon.csv").read_bytes(),
            ImportOptions(category_id=cat.id, mapping=MAPPING),
        )
    assert "1 row" in e.value.fields["rows"]
    assert list(await db.scalars(select(Item))) == []


async def test_apply_skip_invalid_applies_valid_rows(db):
    cat = await resistors(db)
    loc = await make_location(db, "Drawer", code="A1")
    await apply_import(
        db,
        (FIXTURES / "excel_semicolon.csv").read_bytes(),
        ImportOptions(category_id=cat.id, mapping=MAPPING, skip_invalid=True),
    )
    items = {i.name: i for i in await db.scalars(select(Item))}
    assert set(items) == {"Resistor 4k7", "Resistor 10k"}
    assert await stock.on_hand(db, items["Resistor 4k7"].id) == 100
    rows = await stock.item_stock(db, items["Resistor 10k"].id)
    assert rows[0].location_id == loc.id
    moves = list(await db.scalars(select(StockMovement)))
    assert {(m.reason, m.source) for m in moves} == {("import", "import")}


async def test_existing_sku_adds_stock(db):
    cat = await resistors(db)
    loc = await make_location(db, "Drawer", code="A1")
    item = await make_item(db, cat, "R", sku="R-1")
    await stock.add_stock(db, item.id, loc.id, 5)
    data = b"sku,qty,location\nR-1,7,A1\n"
    preview = await apply_import(
        db,
        data,
        ImportOptions(
            category_id=cat.id, mapping={"sku": "sku", "qty": "quantity", "location": "location_code"}
        ),
    )
    assert preview.rows[0].action == "add_stock"
    assert await stock.on_hand(db, item.id) == 12


async def test_unknown_location_code_row_error(db):
    cat = await resistors(db)
    data = b"name,qty,location\nR,1,NOPE\n"
    preview = await preview_import(
        db,
        data,
        ImportOptions(
            category_id=cat.id, mapping={"name": "name", "qty": "quantity", "location": "location_code"}
        ),
    )
    assert "location" in preview.rows[0].errors


async def test_unit_category_rows_create_units(db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        unit_id_pattern="C{seq:4}",
        fields=[{"key": "model", "type": "text"}, {"key": "wrap_color", "type": "text", "scope": "unit"}],
    )
    data = b"name,model,wrap,serial\nSamsung 30Q,30Q,pink,SN1\nSamsung 30Q,30Q,blue,SN2\n"
    mapping = {"name": "name", "model": "attr.model", "wrap": "attr.wrap_color", "serial": "serial_number"}
    preview = await apply_import(db, data, ImportOptions(category_id=cat.id, mapping=mapping))
    assert [r.action for r in preview.rows] == ["create_unit", "create_unit"]
    items = list(await db.scalars(select(Item)))
    assert len(items) == 1 and items[0].attrs == {"model": "30Q"}
    from pick2light.core.units import list_units

    units = await list_units(db, items[0].id)
    assert [(u.unit_code, u.attrs["wrap_color"], u.serial_number) for u in units] == [
        ("C0001", "pink", "SN1"),
        ("C0002", "blue", "SN2"),
    ]


async def test_full_json_export_contains_all_sections(db):
    cat = await resistors(db)
    item = await make_item(db, cat, "R")
    loc = await make_location(db, "Drawer")
    await stock.add_stock(db, item.id, loc.id, 1)
    cells = await make_category(db, "Cells", tracking_mode="unit")
    await make_unit(db, await make_item(db, cells, "30Q"))
    data = await csv_io.export_full_json(db)
    assert set(data) >= {
        "version",
        "categories",
        "location_types",
        "locations",
        "items",
        "units",
        "stock",
        "log_entries",
        "purchase_sources",
        "attachments",
    }
    assert data["categories"][0]["fields"] and len(data["items"]) == 2
    json.dumps(data)


async def test_io_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Thing"})
    r = await client.get("/api/v1/export/items.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "Thing" in r.text
    assert (await client.get("/api/v1/export/bogus.csv")).status_code == 404
    r = await client.get("/api/v1/export/full.json")
    assert r.json()["items"][0]["name"] == "Thing"
    opts = json.dumps({"category_id": cat["id"], "mapping": {"name": "name"}})
    r = await client.post(
        "/api/v1/import/csv/preview",
        data={"options": opts},
        files={"file": ("a.csv", b"name\nGlue\n", "text/csv")},
    )
    assert r.status_code == 200 and r.json()["rows"][0]["action"] == "create"
    r = await client.post(
        "/api/v1/import/csv/apply",
        data={"options": opts},
        files={"file": ("a.csv", b"name\nGlue\n", "text/csv")},
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/search", params={"q": "Glue"})).json()["total"] == 1
