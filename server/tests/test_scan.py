from sqlalchemy import func, select

from pick2light.core.barcodes import register_barcode
from pick2light.core.stock import add_stock
from pick2light.models import StockMovement
from tests.factories import make_category, make_item, make_location, make_unit


async def scan(client, code, **kw):
    r = await client.post("/api/v1/scan", json={"code": code, **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def bulk(db, qty=None, **item_kw):
    item = await make_item(db, await make_category(db, "Resistors"), "10k", **item_kw)
    loc = await make_location(db, "Drawer A")
    if qty:
        await add_stock(db, item.id, loc.id, qty)
    return item, loc


async def movements(db, item_id):
    return list(
        await db.scalars(
            select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.id)
        )
    )


async def test_find_item_by_sku_lists_locations(client, db):
    item, loc = await bulk(db, 5)
    body = await scan(client, item.sku)
    assert (body["kind"], body["action"]) == ("item", "found")
    assert body["item"]["id"] == item.id
    assert [(r["location_id"], r["quantity"]) for r in body["locations"]] == [(loc.id, 5)]


async def test_find_unit_by_code(client, db):
    category = await make_category(db, "Boards", tracking_mode="unit")
    item = await make_item(db, category)
    loc = await make_location(db)
    unit = await make_unit(db, item, location_id=loc.id)
    body = await scan(client, unit.unit_code)
    assert (body["kind"], body["action"]) == ("unit", "found")
    assert body["unit"]["id"] == unit.id
    assert body["location"]["id"] == loc.id


async def test_find_location(client, db):
    loc = await make_location(db)
    body = await scan(client, loc.code)
    assert (body["kind"], body["action"], body["location"]["id"]) == ("location", "found", loc.id)


async def test_find_trims_whitespace_and_newline(client, db):
    item, _ = await bulk(db)
    body = await scan(client, f"  {item.sku}\r\n")
    assert body["kind"] == "item"


async def test_check_out_single_location(client, db):
    item, loc = await bulk(db, 5)
    body = await scan(client, item.sku, mode="check_out", quantity=2)
    assert body["action"] == "checked_out"
    assert body["movement_id"] is not None
    assert body["item"]["on_hand"] == 3


async def test_check_out_multiple_locations_needs_location(client, db):
    item, loc = await bulk(db, 5)
    other = await make_location(db, "Drawer B")
    await add_stock(db, item.id, other.id, 4)
    body = await scan(client, item.sku, mode="check_out")
    assert body["action"] == "needs_location"
    assert {r["location_id"] for r in body["locations"]} == {loc.id, other.id}
    assert body["movement_id"] is None
    assert len(await movements(db, item.id)) == 2  # only the two check-ins


async def test_check_out_with_location_id(client, db):
    item, loc = await bulk(db, 5)
    other = await make_location(db, "Drawer B")
    await add_stock(db, item.id, other.id, 4)
    body = await scan(client, item.sku, mode="check_out", quantity=3, location_id=other.id)
    assert body["action"] == "checked_out"
    assert body["item"]["on_hand"] == 6


async def test_check_in_default_location(client, db):
    loc = await make_location(db, "Home")
    item = await make_item(db, await make_category(db), default_location_id=loc.id)
    body = await scan(client, item.sku, mode="check_in", quantity=7)
    assert body["action"] == "checked_in"
    assert body["item"]["on_hand"] == 7


async def test_check_in_without_default_needs_location(client, db):
    item, loc = await bulk(db)
    body = await scan(client, item.sku, mode="check_in")
    assert (body["action"], body["locations"]) == ("needs_location", [])
    body = await scan(client, item.sku, mode="check_in", location_id=loc.id)
    assert body["action"] == "checked_in"


async def test_consume_bulk_records_consume(client, db):
    item, loc = await bulk(db, 5)
    body = await scan(client, item.sku, mode="consume", quantity=2)
    assert body["action"] == "consumed"
    assert (await movements(db, item.id))[-1].reason == "consume"


async def test_unit_check_out_then_in(client, db):
    item = await make_item(db, await make_category(db, "Boards", tracking_mode="unit"))
    loc = await make_location(db)
    unit = await make_unit(db, item, location_id=loc.id)
    out = await scan(client, unit.unit_code, mode="check_out")
    assert (out["action"], out["unit"]["status"]) == ("checked_out", "checked_out")
    back = await scan(client, unit.unit_code, mode="check_in")
    assert (back["action"], back["unit"]["status"]) == ("checked_in", "in_stock")


async def test_consume_unit(client, db):
    item = await make_item(db, await make_category(db, "Boards", tracking_mode="unit"))
    unit = await make_unit(db, item, location_id=(await make_location(db)).id)
    body = await scan(client, unit.unit_code, mode="consume")
    assert (body["action"], body["unit"]["status"]) == ("consumed", "consumed")


async def test_location_in_check_out_mode_error(client, db):
    loc = await make_location(db)
    body = await scan(client, loc.code, mode="check_out")
    assert (body["kind"], body["action"]) == ("location", "error")
    assert body["message"] == "Scan an item or unit in this mode"


async def test_unknown_code_recorded(client):
    for _ in range(2):
        body = await scan(client, "NOPE-1")
        assert (body["kind"], body["action"]) == ("unknown", "found")
    await scan(client, "NOPE-2")
    r = await client.get("/api/v1/scan/unknown")
    assert r.json() == ["NOPE-2", "NOPE-1"]
    assert (await client.delete("/api/v1/scan/unknown/NOPE-2")).status_code == 204
    assert (await client.get("/api/v1/scan/unknown")).json() == ["NOPE-1"]


async def test_insufficient_stock_is_error_action(client, db):
    item, loc = await bulk(db, 2)
    body = await scan(client, item.sku, mode="check_out", quantity=5)
    assert body["action"] == "error"
    assert body["message"]
    # The failed scan left nothing behind: only the original check-in exists.
    assert [m.reason for m in await movements(db, item.id)] == ["check_in"]
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == 1


async def test_movement_source_is_scan(client, db):
    item, loc = await bulk(db, 5)
    body = await scan(client, item.sku, mode="check_out")
    movement = await db.get(StockMovement, body["movement_id"])
    assert movement.source == "scan"


async def test_trashed_item_is_error(client, db):
    item, _ = await bulk(db)
    await register_barcode(db, "MFR-9", "item", item.id, "manufacturer")
    assert (await client.delete(f"/api/v1/items/{item.id}")).status_code == 204
    body = await scan(client, "MFR-9")
    assert (body["kind"], body["action"]) == ("item", "error")
    assert "trash" in body["message"]
    assert (await client.get("/api/v1/scan/unknown")).json() == []


async def test_delete_unknown_code_with_slash(client):
    await scan(client, "A/B")
    assert (await client.get("/api/v1/scan/unknown")).json() == ["A/B"]
    assert (await client.delete("/api/v1/scan/unknown/A%2FB")).status_code == 204
    assert (await client.get("/api/v1/scan/unknown")).json() == []


async def test_unit_already_checked_out_is_error_without_movement(client, db):
    item = await make_item(db, await make_category(db, "Boards", tracking_mode="unit"))
    unit = await make_unit(db, item, location_id=(await make_location(db)).id)
    await scan(client, unit.unit_code, mode="check_out")
    before = len(await movements(db, item.id))
    body = await scan(client, unit.unit_code, mode="check_out")
    assert (body["kind"], body["action"]) == ("unit", "error")
    assert len(await movements(db, item.id)) == before
