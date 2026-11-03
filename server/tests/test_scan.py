from collections import deque

from factories import make_category, make_item, make_location, make_unit

from pick2light.core import stock
from pick2light.core.items import ItemPatch, update_item
from pick2light.core.scan import ScanRequest, handle_scan
from pick2light.core.units import get_unit


async def bulk(db, qty=10, second=False):
    cat = await make_category(db, "Screws")
    item = await make_item(db, cat, "M3x10")
    a1 = await make_location(db, "Drawer A1")
    await stock.add_stock(db, item.id, a1.id, qty)
    a2 = None
    if second:
        a2 = await make_location(db, "Drawer A2")
        await stock.add_stock(db, item.id, a2.id, qty)
    return item, a1, a2


async def cell(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cat, "30Q")
    box = await make_location(db, "Cell box")
    unit = await make_unit(db, item, location_id=box.id)
    return item, box, unit


async def scan(db, code, unknown=None, **kw):
    return await handle_scan(
        db, ScanRequest(code=code, **kw), unknown if unknown is not None else deque(maxlen=50)
    )


async def test_find_item_by_sku_lists_locations(db):
    item, a1, a2 = await bulk(db, second=True)
    r = await scan(db, item.sku)
    assert (r.kind, r.action) == ("item", "found") and r.item.id == item.id
    assert sorted(x.location_id for x in r.locations) == sorted([a1.id, a2.id])


async def test_find_unit_by_code(db):
    item, box, unit = await cell(db)
    r = await scan(db, unit.unit_code)
    assert (r.kind, r.action) == ("unit", "found") and r.unit.id == unit.id
    assert [x.id for x in r.locations] == [box.id]


async def test_find_location(db):
    box = await make_location(db, "Box")
    r = await scan(db, box.code)
    assert (r.kind, r.action) == ("location", "found") and r.location.id == box.id


async def test_find_trims_whitespace_and_newline(db):
    item, _, _ = await bulk(db)
    r = await scan(db, f"  {item.sku}\r\n")
    assert r.kind == "item"


async def test_check_out_single_location(db):
    item, a1, _ = await bulk(db)
    r = await scan(db, item.sku, mode="check_out", quantity=4)
    assert r.action == "checked_out" and r.movement_id
    assert await stock.on_hand(db, item.id) == 6
    assert "4" in r.message and "Drawer A1" in r.message


async def test_check_out_multiple_locations_needs_location(db):
    item, a1, a2 = await bulk(db, second=True)
    r = await scan(db, item.sku, mode="check_out")
    assert r.action == "needs_location" and len(r.locations) == 2


async def test_check_out_with_location_id(db):
    item, a1, a2 = await bulk(db, second=True)
    r = await scan(db, item.sku, mode="check_out", location_id=a2.id, quantity=3)
    assert r.action == "checked_out"
    assert {x.location_id: x.quantity for x in await stock.item_stock(db, item.id)} == {a1.id: 10, a2.id: 7}


async def test_check_in_default_location(db):
    item, a1, _ = await bulk(db)
    await update_item(db, item.id, ItemPatch(default_location_id=a1.id))
    r = await scan(db, item.sku, mode="check_in", quantity=5)
    assert r.action == "checked_in" and await stock.on_hand(db, item.id) == 15


async def test_check_in_without_default_needs_location(db):
    item, _, _ = await bulk(db)
    r = await scan(db, item.sku, mode="check_in")
    assert r.action == "needs_location" and r.locations == []


async def test_unit_check_out_then_in(db):
    _, box, unit = await cell(db)
    assert (await scan(db, unit.unit_code, mode="check_out")).action == "checked_out"
    assert (await get_unit(db, unit.id)).status == "checked_out"
    assert (await scan(db, unit.unit_code, mode="check_in")).action == "checked_in"
    assert (await get_unit(db, unit.id)).status == "in_stock"


async def test_consume_unit(db):
    _, _, unit = await cell(db)
    r = await scan(db, unit.unit_code, mode="consume")
    assert r.action == "consumed" and r.unit.status == "consumed"


async def test_location_in_check_out_mode_error(db):
    box = await make_location(db, "Box")
    r = await scan(db, box.code, mode="check_out")
    assert r.action == "error" and r.message == "Scan an item or unit in this mode"


async def test_unknown_code_recorded(client):
    for _ in range(2):
        r = await client.post("/api/v1/scan", json={"code": "4006381333931"})
        assert r.json()["kind"] == "unknown"
    await client.post("/api/v1/scan", json={"code": "OTHER-1"})
    assert (await client.get("/api/v1/scan/unknown")).json() == ["OTHER-1", "4006381333931"]
    assert (await client.delete("/api/v1/scan/unknown/OTHER-1")).status_code == 204
    assert (await client.get("/api/v1/scan/unknown")).json() == ["4006381333931"]


async def test_insufficient_stock_is_error_action(db):
    item, _, _ = await bulk(db, qty=2)
    r = await scan(db, item.sku, mode="check_out", quantity=5)
    assert r.action == "error" and "Only 2" in r.message
    assert await stock.on_hand(db, item.id) == 2


async def test_movement_source_is_scan(db):
    item, _, _ = await bulk(db)
    await scan(db, item.sku, mode="consume", quantity=1)
    moves = await stock.list_movements(db, item_id=item.id)
    assert moves[0].source == "scan" and moves[0].reason == "consume"


async def test_unit_item_sku_in_check_out_mode_asks_for_unit(db):
    item, _, _ = await cell(db)
    r = await scan(db, item.sku, mode="check_out")
    assert r.action == "error" and "unit" in r.message.lower()
