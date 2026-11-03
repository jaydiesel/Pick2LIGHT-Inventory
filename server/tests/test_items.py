import pytest
from sqlalchemy import select

from pick2light.core.barcodes import lookup_barcode
from pick2light.core.categories import FieldDefIn, add_field, effective_field_defs
from pick2light.core.items import (
    ItemIn,
    ItemPatch,
    create_item,
    delete_item,
    get_item,
    get_item_out,
    update_item,
)
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Item
from tests.factories import make_category, make_item, make_unit

RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}
SCREW_FIELDS = [
    {"key": "thread", "type": "text"},
    {"key": "length", "type": "number"},
    {
        "key": "head",
        "type": "select",
        "options": [
            {"value": "socket_head", "label": "Socket head", "sku_code": "SHCS"},
            {"value": "pan", "label": "Pan"},
        ],
    },
]


async def test_create_item_generates_sku(db):
    resistors = await make_category(db, "Resistors")
    first = await make_item(db, resistors, "10k")
    second = await make_item(db, resistors, "22k")
    assert first.sku == "RESI-0001"
    assert second.sku == "RESI-0002"


async def test_create_item_pattern_sku(db):
    screws = await make_category(
        db,
        "Screws",
        sku_prefix="SCR",
        sku_pattern="{prefix}-{thread}-{length}-{head}",
        fields=SCREW_FIELDS,
    )
    item = await make_item(
        db, screws, "M3x10", attrs={"thread": "M3", "length": 10, "head": "socket_head"}
    )
    assert item.sku == "SCR-M3-10-SHCS"


async def test_empty_rendered_sku_falls_back(db):
    category = await make_category(db, "Odd", sku_pattern="{thread}", fields=[SCREW_FIELDS[0]])
    item = await make_item(db, category, "No thread")
    assert item.sku == "ITEM-0001"


async def test_manual_sku_sanitized_and_unique(db):
    category = await make_category(db, "Misc")
    first = await make_item(db, category, "A", sku="m3/10")
    second = await make_item(db, category, "B", sku="m3/10")
    assert (first.sku, second.sku) == ("M3-10", "M3-10-2")


async def test_manual_sku_with_no_usable_characters_refused(db):
    category = await make_category(db, "Misc")
    with pytest.raises(ValidationFailed) as exc:
        await make_item(db, category, "A", sku="///")
    assert "sku" in exc.value.fields


async def test_soft_deleted_item_keeps_its_sku_reserved(db):
    category = await make_category(db, "Misc")
    first = await make_item(db, category, "A", sku="KEEP")
    await delete_item(db, first.id)
    second = await make_item(db, category, "B", sku="KEEP")
    assert second.sku == "KEEP-2"


async def test_sku_registered_as_barcode(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A", sku="ABC-1")
    barcode = await lookup_barcode(db, "ABC-1")
    assert (barcode.target_type, barcode.target_id, barcode.kind) == ("item", item.id, "sku")


async def test_attrs_validated(db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    with pytest.raises(ValidationFailed) as exc:
        await make_item(db, category, "Bad", attrs={"resistance": "lots"})
    assert "resistance" in exc.value.fields
    with pytest.raises(ValidationFailed) as exc:
        await make_item(db, category, "Bad", attrs={"nope": 1})
    assert exc.value.fields == {"nope": "unknown field"}


async def test_unit_scope_values_rejected_on_item(db):
    category = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "voltage", "type": "number", "scope": "unit"}],
    )
    with pytest.raises(ValidationFailed):
        await make_item(db, category, "18650", attrs={"voltage": 3.7})


async def test_attrs_display_formats_si(db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    item = await make_item(db, category, "4k7", attrs={"resistance": "4.7k"})
    assert item.attrs == {"resistance": 4700}
    out = await get_item_out(db, item.id)
    assert out.attrs_display["resistance"] == "4.7kΩ"
    assert [p.name for p in out.category_path] == ["Resistors"]
    assert out.tracking_mode == "bulk"
    assert out.on_hand == 0


async def test_search_text_includes_si_alternates(db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    item = await make_item(
        db, category, "Metal film", description="Précis", attrs={"resistance": 4700}
    )
    for token in ("4k7", "4.7kΩ", "4700", "metal film", item.sku.lower()):
        assert token.lower() in item.search_text.lower()
    await db.refresh(item, ["search_vector"])
    assert "4k7" in item.search_vector


async def test_search_text_is_nfkc_normalised(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "Ａ１ ½", description="ﬁne")
    assert "A1 1⁄2" in item.search_text
    assert "fine" in item.search_text


async def test_item_loads_after_field_removed(db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    item = await make_item(db, category, "4k7", attrs={"resistance": 4700})
    (definition,) = await effective_field_defs(db, category.id)
    await db.delete(definition)
    await db.flush()
    out = await get_item_out(db, item.id)
    assert out.attrs == {"resistance": 4700}
    assert "resistance" not in out.attrs_display


async def test_change_category_revalidates(db):
    resistors = await make_category(db, "Resistors", fields=[RESISTANCE])
    caps = await make_category(
        db, "Capacitors", fields=[{"key": "voltage", "type": "number", "required": True}]
    )
    item = await make_item(db, resistors, "4k7", attrs={"resistance": 4700})
    with pytest.raises(ValidationFailed) as exc:
        await update_item(db, item.id, ItemPatch(category_id=caps.id))
    assert exc.value.fields == {"voltage": "required"}
    updated = await update_item(db, item.id, ItemPatch(category_id=caps.id, attrs={"voltage": 16}))
    assert updated.category_id == caps.id
    assert updated.attrs == {"voltage": 16}  # stale resistance dropped on category change


async def test_stale_keys_kept_on_ordinary_update(db):
    category = await make_category(db, "Resistors", fields=[RESISTANCE])
    item = await make_item(db, category, "4k7", attrs={"resistance": 4700})
    (definition,) = await effective_field_defs(db, category.id)
    await db.delete(definition)
    await db.flush()
    updated = await update_item(db, item.id, ItemPatch(name="Renamed"))
    assert updated.name == "Renamed"
    assert updated.attrs == {"resistance": 4700}


async def test_update_attrs_merges_and_null_removes(db):
    category = await make_category(
        db, "Misc", fields=[{"key": "a", "type": "text"}, {"key": "b", "type": "text"}]
    )
    item = await make_item(db, category, "X", attrs={"a": "1", "b": "2"})
    updated = await update_item(db, item.id, ItemPatch(attrs={"a": "9", "b": None}))
    assert updated.attrs == {"a": "9"}


async def test_change_sku_reregisters_barcode(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A", sku="OLD-1")
    other = await make_item(db, category, "B", sku="TAKEN")
    updated = await update_item(db, item.id, ItemPatch(sku="new/1"))
    assert updated.sku == "NEW-1"
    assert await lookup_barcode(db, "OLD-1") is None
    assert (await lookup_barcode(db, "NEW-1")).target_id == item.id
    with pytest.raises(Conflict):
        await update_item(db, item.id, ItemPatch(sku="taken"))
    assert other.sku == "TAKEN"


async def test_update_keeps_manufacturer_barcodes_when_sku_changes(db):
    from pick2light.core.barcodes import register_barcode

    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A")
    await register_barcode(db, "5012345678900", "item", item.id, "manufacturer")
    await update_item(db, item.id, ItemPatch(sku="NEW-2"))
    assert (await lookup_barcode(db, "5012345678900")).target_id == item.id


async def test_update_missing_default_location_refused(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A")
    with pytest.raises(ValidationFailed) as exc:
        await update_item(db, item.id, ItemPatch(default_location_id=99999))
    assert "default_location_id" in exc.value.fields


async def test_create_in_missing_category(db):
    with pytest.raises(NotFound):
        await create_item(db, ItemIn(category_id=99999, name="X"))


async def test_delete_item_is_soft_and_frees_barcode(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A", sku="GONE-1")
    await delete_item(db, item.id)
    assert await lookup_barcode(db, "GONE-1") is None
    with pytest.raises(NotFound):
        await get_item(db, item.id)
    assert (await db.scalar(select(Item).where(Item.id == item.id))).deleted_at is not None


async def test_delete_item_with_active_units_refused(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    with pytest.raises(Conflict):
        await delete_item(db, item.id)
    unit.status = "consumed"
    await db.flush()
    await delete_item(db, item.id)


async def test_on_hand_counts_in_stock_units(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    first = await make_unit(db, item)
    await make_unit(db, item)
    first.status = "checked_out"
    await db.flush()
    out = await get_item_out(db, item.id)
    assert (out.tracking_mode, out.on_hand) == ("unit", 1)


async def test_cannot_move_item_with_units_to_bulk_category(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    bulk = await make_category(db, "Bulk")
    item = await make_item(db, cells, "18650")
    await make_unit(db, item)
    from pick2light.errors import InvalidOperation

    with pytest.raises(InvalidOperation):
        await update_item(db, item.id, ItemPatch(category_id=bulk.id))


async def test_add_field_after_items_exist_does_not_break_get(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "A")
    await add_field(
        db, category.id, FieldDefIn(key="notes_x", label="N", type="text", required=True)
    )
    assert (await get_item_out(db, item.id)).id == item.id
