import pytest
from factories import RES_FIELDS, SCREW_FIELDS, make_category, make_item

from pick2light.core.barcodes import lookup_barcode
from pick2light.core.categories import (
    CategoryPatch,
    delete_category,
    delete_field,
    field_defs_out,
    update_category,
)
from pick2light.core.items import ItemPatch, delete_item, get_item_out, update_item
from pick2light.errors import Conflict, ValidationFailed


async def test_create_item_generates_sku(db):
    cat = await make_category(db, "Resistors")
    item = await make_item(db, cat, "Resistor 10k")
    assert item.sku == "RESI-0001"


async def test_create_item_pattern_sku(db):
    cat = await make_category(
        db, "Screws", sku_prefix="SCR", sku_pattern="SCR-{thread}-{length}-{head}", fields=SCREW_FIELDS
    )
    item = await make_item(db, cat, "M3x10", attrs={"thread": "M3", "length": "10", "head": "socket_head"})
    assert item.sku == "SCR-M3-10-SHCS"


async def test_manual_sku_sanitized_and_unique(db):
    cat = await make_category(db, "Screws")
    a = await make_item(db, cat, "A", sku="m3/10")
    b = await make_item(db, cat, "B", sku="m3/10")
    assert (a.sku, b.sku) == ("m3-10", "m3-10-2")


async def test_sku_registered_as_barcode(db):
    cat = await make_category(db, "Resistors")
    item = await make_item(db, cat, "R")
    bc = await lookup_barcode(db, item.sku)
    assert bc.target_type == "item" and bc.target_id == item.id and bc.kind == "sku"


async def test_attrs_validated(db):
    cat = await make_category(db, "Resistors", fields=RES_FIELDS)
    with pytest.raises(ValidationFailed) as e:
        await make_item(db, cat, "R", attrs={"resistance": "lots"})
    assert "resistance" in e.value.fields


async def test_attrs_display_formats_si(db):
    cat = await make_category(db, "Resistors", fields=RES_FIELDS)
    item = await make_item(db, cat, "R", attrs={"resistance": "4k7", "package": "0805"})
    out = await get_item_out(db, item.id)
    assert out.attrs["resistance"] == 4700
    assert out.attrs_display["resistance"] == "4.7kΩ"
    assert out.tracking_mode == "bulk"
    assert [p.name for p in out.category_path] == ["Resistors"]


async def test_item_loads_after_field_removed(db):
    cat = await make_category(db, "Resistors", fields=RES_FIELDS)
    item = await make_item(db, cat, "R", attrs={"resistance": 4700, "package": "0805"})
    pkg = next(f for f in await field_defs_out(db, cat.id) if f.key == "package")
    await delete_field(db, pkg.id)
    out = await get_item_out(db, item.id)
    assert out.attrs["package"] == "0805"
    assert "package" not in out.attrs_display
    updated = await update_item(db, item.id, ItemPatch(attrs={"resistance": 1000}))
    assert updated.attrs == {"resistance": 1000, "package": "0805"}


async def test_change_category_revalidates(db):
    res = await make_category(db, "Resistors", fields=RES_FIELDS)
    caps = await make_category(
        db, "Caps", fields=[{"key": "package", "type": "select", "options": [{"value": "1206"}]}]
    )
    item = await make_item(db, res, "R", attrs={"resistance": 4700, "package": "0805"})
    with pytest.raises(ValidationFailed) as e:
        await update_item(db, item.id, ItemPatch(category_id=caps.id))
    assert "package" in e.value.fields
    moved = await update_item(db, item.id, ItemPatch(category_id=caps.id, attrs={"package": "1206"}))
    assert moved.attrs == {"package": "1206"}


async def test_update_sku_reregisters_barcode(db):
    cat = await make_category(db, "Resistors")
    item = await make_item(db, cat, "R")
    old = item.sku
    await update_item(db, item.id, ItemPatch(sku="RES-10K"))
    assert await lookup_barcode(db, old) is None
    assert (await lookup_barcode(db, "RES-10K")).target_id == item.id


async def test_search_text_contains_si_alternates(db):
    cat = await make_category(db, "Resistors", fields=RES_FIELDS)
    item = await make_item(db, cat, "Resistor", attrs={"resistance": 4700})
    assert "4k7" in item.search_text and "4.7kΩ" in item.search_text and item.sku in item.search_text


async def test_delete_category_with_items_refused(db):
    cat = await make_category(db, "Resistors")
    await make_item(db, cat, "R")
    with pytest.raises(Conflict):
        await delete_category(db, cat.id)


async def test_tracking_mode_change_with_items_refused(db):
    cat = await make_category(db, "Cells")
    await make_item(db, cat, "Cell")
    with pytest.raises(Conflict):
        await update_category(db, cat.id, CategoryPatch(tracking_mode="unit"))


async def test_delete_item_removes_barcode(db):
    cat = await make_category(db, "Resistors")
    item = await make_item(db, cat, "R")
    await delete_item(db, item.id)
    assert await lookup_barcode(db, item.sku) is None
