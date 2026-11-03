import pytest

from pick2light.core.barcodes import lookup_barcode, register_barcode
from pick2light.core.items import get_item_out
from pick2light.core.units import (
    UnitIn,
    UnitPatch,
    create_unit,
    delete_unit,
    get_unit,
    get_unit_out,
    update_unit,
)
from pick2light.errors import Conflict, InvalidOperation, NotFound, ValidationFailed
from tests.factories import make_category, make_item, make_location, make_unit


async def test_create_unit_requires_unit_category(db):
    bulk = await make_category(db, "Resistors")
    item = await make_item(db, bulk, "10k")
    with pytest.raises(InvalidOperation):
        await create_unit(db, UnitIn(item_id=item.id))


async def test_create_unit_for_missing_item(db):
    with pytest.raises(NotFound):
        await create_unit(db, UnitIn(item_id=99999))


async def test_unit_code_generated(db):
    cells = await make_category(db, "Cells", tracking_mode="unit", unit_id_pattern="C{seq:4}")
    item = await make_item(db, cells, "18650")
    first = await make_unit(db, item)
    second = await make_unit(db, item)
    assert (first.unit_code, second.unit_code) == ("C0001", "C0002")
    assert (first.status, first.condition) == ("in_stock", "untested")
    barcode = await lookup_barcode(db, "C0001")
    assert (barcode.target_type, barcode.target_id, barcode.kind) == ("unit", first.id, "unit_code")


async def test_unit_code_default_pattern_and_fallback(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    assert (await make_unit(db, item)).unit_code == "CELL0001"
    odd = await make_category(db, "Odd", tracking_mode="unit", unit_id_pattern="{nothing}")
    odd_item = await make_item(db, odd, "Thing")
    assert (await make_unit(db, odd_item)).unit_code == "UNIT-0001"


async def test_manual_unit_code_sanitized_and_unique(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    first = await make_unit(db, item, unit_code="c 1")
    second = await make_unit(db, item, unit_code="c 1")
    assert (first.unit_code, second.unit_code) == ("C-1", "C-1-2")


async def test_unit_serial_registered(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="SN-123")
    barcode = await lookup_barcode(db, "SN-123")
    assert (barcode.target_type, barcode.target_id, barcode.kind) == (
        "unit",
        unit.id,
        "manufacturer",
    )
    with pytest.raises(Conflict):
        await make_unit(db, item, serial_number="SN-123")


async def test_unit_attrs_validated_with_unit_scope(db):
    cells = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[
            {"key": "capacity", "type": "number", "number_unit": "mAh", "scope": "unit"},
            {"key": "chemistry", "type": "text"},
        ],
    )
    item = await make_item(db, cells, "18650", attrs={"chemistry": "Li-ion"})
    with pytest.raises(ValidationFailed) as exc:
        await make_unit(db, item, attrs={"chemistry": "x"})
    assert "chemistry" in exc.value.fields
    unit = await make_unit(db, item, attrs={"capacity": "2.5k"})
    assert unit.attrs == {"capacity": 2500}
    out = await get_unit_out(db, unit.id)
    assert out.attrs_display == {"capacity": "2.5kmAh"}
    assert (out.item.id, out.item.sku) == (item.id, item.sku)


async def test_unit_out_has_location_path(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    cabinet = await make_location(db, "Cabinet")
    drawer = await make_location(db, "Drawer", parent=cabinet)
    unit = await make_unit(db, item, location_id=drawer.id)
    out = await get_unit_out(db, unit.id)
    assert [p.name for p in out.location_path] == ["Cabinet", "Drawer"]
    with pytest.raises(ValidationFailed):
        await make_unit(db, item, location_id=99999)


async def test_update_unit_serial_and_condition(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="OLD")
    await register_barcode(db, "EAN-1", "unit", unit.id, "manufacturer")
    updated = await update_unit(db, unit.id, UnitPatch(serial_number="NEW", condition="faulty"))
    assert (updated.serial_number, updated.condition) == ("NEW", "faulty")
    assert await lookup_barcode(db, "OLD") is None
    assert (await lookup_barcode(db, "NEW")).target_id == unit.id
    assert (await lookup_barcode(db, "EAN-1")).target_id == unit.id
    cleared = await update_unit(db, unit.id, UnitPatch(serial_number=None))
    assert cleared.serial_number is None
    assert await lookup_barcode(db, "NEW") is None


async def test_delete_unit_soft_removes_barcodes(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="SN-9")
    await delete_unit(db, unit.id)
    assert await lookup_barcode(db, unit.unit_code) is None
    assert await lookup_barcode(db, "SN-9") is None
    with pytest.raises(NotFound):
        await get_unit(db, unit.id)
    again = await make_unit(db, item, unit_code=unit.unit_code)
    assert again.unit_code == f"{unit.unit_code}-2"  # deleted units keep their code reserved
    assert (await get_item_out(db, item.id)).on_hand == 1
