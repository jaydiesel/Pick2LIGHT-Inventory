import pytest
from factories import make_category, make_item, make_location, make_unit

from pick2light.core.barcodes import lookup_barcode
from pick2light.core.units import UnitPatch, get_unit_out, update_unit
from pick2light.errors import InvalidOperation, ValidationFailed

CELL_FIELDS = [
    {"key": "model", "type": "text"},
    {"key": "wrap_color", "type": "text", "scope": "unit"},
]


async def cells(db):
    return await make_category(
        db, "Cells", tracking_mode="unit", sku_prefix="CELL", unit_id_pattern="C{seq:4}", fields=CELL_FIELDS
    )


async def test_create_unit_requires_unit_category(db):
    cat = await make_category(db, "Screws")
    item = await make_item(db, cat, "M3")
    with pytest.raises(InvalidOperation):
        await make_unit(db, item)


async def test_unit_code_generated(db):
    item = await make_item(db, await cells(db), "30Q")
    assert (await make_unit(db, item)).unit_code == "C0001"
    assert (await make_unit(db, item)).unit_code == "C0002"


async def test_unit_attrs_scope(db):
    item = await make_item(db, await cells(db), "30Q", attrs={"model": "30Q"})
    unit = await make_unit(db, item, attrs={"wrap_color": "pink"})
    assert unit.attrs == {"wrap_color": "pink"}
    with pytest.raises(ValidationFailed):
        await make_unit(db, item, attrs={"model": "x"})


async def test_unit_serial_registered(db):
    item = await make_item(db, await cells(db), "Drive")
    unit = await make_unit(db, item, serial_number="WD-123")
    bc = await lookup_barcode(db, "WD-123")
    assert bc.target_type == "unit" and bc.target_id == unit.id and bc.kind == "manufacturer"
    await update_unit(db, unit.id, UnitPatch(serial_number="WD-999"))
    assert await lookup_barcode(db, "WD-123") is None
    assert (await lookup_barcode(db, "WD-999")).target_id == unit.id


async def test_unit_out(db):
    loc = await make_location(db, "Drawer")
    item = await make_item(db, await cells(db), "30Q")
    unit = await make_unit(db, item, location_id=loc.id, attrs={"wrap_color": "pink"})
    out = await get_unit_out(db, unit.id)
    assert out.item.sku == item.sku and out.status == "in_stock" and out.condition == "untested"
    assert [p.name for p in out.location_path] == ["Drawer"]
    assert out.attrs_display == {"wrap_color": "pink"}
