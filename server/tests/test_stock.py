import asyncio

import pytest
from factories import make_category, make_item, make_location, make_unit

from pick2light.core import stock
from pick2light.core.locations import delete_location
from pick2light.core.units import get_unit
from pick2light.errors import Conflict, InvalidOperation


async def bulk_setup(db, qty=0):
    cat = await make_category(db, "Screws")
    item = await make_item(db, cat, "M3x10", min_stock=50)
    loc = await make_location(db, "Drawer A1")
    if qty:
        await stock.add_stock(db, item.id, loc.id, qty)
    return item, loc


async def unit_setup(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cat, "30Q")
    loc = await make_location(db, "Cell box")
    unit = await make_unit(db, item, location_id=loc.id)
    return item, loc, unit


async def test_add_and_remove_bulk(db):
    item, loc = await bulk_setup(db)
    m = await stock.add_stock(db, item.id, loc.id, 100)
    assert m.quantity_delta == 100 and m.to_location_id == loc.id and m.reason == "check_in"
    m = await stock.remove_stock(db, item.id, loc.id, 30, reason="consume")
    assert m.quantity_delta == -30 and m.from_location_id == loc.id and m.reason == "consume"
    assert await stock.on_hand(db, item.id) == 70


async def test_remove_more_than_present_refused(db):
    item, loc = await bulk_setup(db, qty=3)
    with pytest.raises(InvalidOperation, match="Only 3"):
        await stock.remove_stock(db, item.id, loc.id, 5)


async def test_non_positive_quantity_refused(db):
    item, loc = await bulk_setup(db)
    with pytest.raises(InvalidOperation):
        await stock.add_stock(db, item.id, loc.id, 0)


async def test_move_stock(db):
    item, loc = await bulk_setup(db, qty=10)
    other = await make_location(db, "Drawer A2")
    await stock.move_stock(db, item.id, loc.id, other.id, 4)
    rows = {r.location_id: r.quantity for r in await stock.item_stock(db, item.id)}
    assert rows == {loc.id: 6, other.id: 4}


async def test_adjust_writes_delta(db):
    item, loc = await bulk_setup(db, qty=10)
    m = await stock.adjust_stock(db, item.id, loc.id, 7)
    assert m.quantity_delta == -3 and m.reason == "adjust"
    assert await stock.adjust_stock(db, item.id, loc.id, 7) is None


async def test_zero_rows_hidden(db):
    item, loc = await bulk_setup(db, qty=2)
    await stock.remove_stock(db, item.id, loc.id, 2)
    assert await stock.item_stock(db, item.id) == []


@pytest.mark.parametrize(
    ("steps", "ok"),
    [
        (["check_out", "check_in"], True),
        (["check_out", "check_out"], False),
        (["check_in"], False),
        (["consume", "check_in"], False),
        (["check_out", "consume"], True),
        (["dispose", "dispose"], False),
    ],
)
async def test_unit_transitions(db, steps, ok):
    _, _, unit = await unit_setup(db)
    funcs = {
        "check_out": stock.check_out_unit,
        "check_in": stock.check_in_unit,
        "consume": stock.consume_unit,
        "dispose": stock.dispose_unit,
    }
    if ok:
        for s in steps:
            await funcs[s](db, unit.id)
    else:
        with pytest.raises(InvalidOperation):
            for s in steps:
                await funcs[s](db, unit.id)


async def test_unit_keeps_home_location_when_checked_out(db):
    item, loc, unit = await unit_setup(db)
    await stock.check_out_unit(db, unit.id)
    u = await get_unit(db, unit.id)
    assert u.status == "checked_out" and u.location_id == loc.id
    assert await stock.on_hand(db, item.id) == 0
    await stock.check_in_unit(db, unit.id)
    await stock.consume_unit(db, unit.id)
    u = await get_unit(db, unit.id)
    assert u.status == "consumed" and u.location_id is None


async def test_unit_create_writes_movement(db):
    item, loc, unit = await unit_setup(db)
    moves = await stock.list_movements(db, unit_id=unit.id)
    assert [(m.reason, m.quantity_delta) for m in moves] == [("create", 1)]


async def test_undo_bulk_add(db):
    item, loc = await bulk_setup(db)
    m = await stock.add_stock(db, item.id, loc.id, 5)
    u = await stock.undo_movement(db, m.id)
    assert u.reason == "undo" and u.reverses_movement_id == m.id
    assert await stock.on_hand(db, item.id) == 0
    moves = await stock.list_movements(db, item_id=item.id)
    assert next(x for x in moves if x.id == m.id).reversed is True


async def test_undo_move(db):
    item, loc = await bulk_setup(db, qty=10)
    other = await make_location(db, "Drawer A2")
    m = await stock.move_stock(db, item.id, loc.id, other.id, 4)
    await stock.undo_movement(db, m.id)
    assert {r.location_id: r.quantity for r in await stock.item_stock(db, item.id)} == {loc.id: 10}


async def test_undo_unit_check_out(db):
    _, _, unit = await unit_setup(db)
    m = await stock.check_out_unit(db, unit.id)
    await stock.undo_movement(db, m.id)
    assert (await get_unit(db, unit.id)).status == "in_stock"


async def test_undo_twice_refused(db):
    item, loc = await bulk_setup(db)
    m = await stock.add_stock(db, item.id, loc.id, 5)
    u = await stock.undo_movement(db, m.id)
    with pytest.raises(Conflict):
        await stock.undo_movement(db, m.id)
    with pytest.raises(Conflict):
        await stock.undo_movement(db, u.id)


async def test_undo_after_consumed_refused(db):
    item, loc = await bulk_setup(db)
    m = await stock.add_stock(db, item.id, loc.id, 5)
    await stock.remove_stock(db, item.id, loc.id, 5, reason="consume")
    with pytest.raises(InvalidOperation):
        await stock.undo_movement(db, m.id)


async def test_low_stock_list(db):
    item, loc = await bulk_setup(db, qty=10)
    rows = await stock.low_stock(db)
    assert [(r.sku, r.on_hand, r.min_stock) for r in rows] == [(item.sku, 10, 50)]
    await stock.add_stock(db, item.id, loc.id, 40)
    assert await stock.low_stock(db) == []


async def test_bulk_op_on_unit_item_refused(db):
    item, loc, _ = await unit_setup(db)
    with pytest.raises(InvalidOperation):
        await stock.add_stock(db, item.id, loc.id, 1)


async def test_delete_location_with_stock_refused(db):
    item, loc = await bulk_setup(db, qty=1)
    with pytest.raises(Conflict):
        await delete_location(db, loc.id)
    _, cell_loc, _ = await unit_setup(db)
    with pytest.raises(Conflict):
        await delete_location(db, cell_loc.id)


async def test_concurrent_check_out_never_negative(committed_db):
    async with committed_db() as s:
        item, loc = await bulk_setup(s, qty=5)
        await s.commit()
        item_id, loc_id = item.id, loc.id

    async def take():
        async with committed_db() as s:
            await stock.remove_stock(s, item_id, loc_id, 4)
            await asyncio.sleep(0.05)
            await s.commit()

    results = await asyncio.gather(take(), take(), return_exceptions=True)
    assert sum(isinstance(r, InvalidOperation) for r in results) == 1
    async with committed_db() as s:
        assert await stock.on_hand(s, item_id) == 1


async def test_stock_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Screws"})).json()
    item = (
        await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "M3", "min_stock": 5})
    ).json()
    loc = (await client.post("/api/v1/locations", json={"name": "A1"})).json()
    r = await client.post(
        "/api/v1/stock/add", json={"item_id": item["id"], "location_id": loc["id"], "quantity": 3}
    )
    assert r.status_code == 200 and r.json()["quantity_delta"] == 3
    assert (await client.get(f"/api/v1/items/{item['id']}")).json()["on_hand"] == 3
    stock_rows = (await client.get(f"/api/v1/items/{item['id']}/stock")).json()
    assert stock_rows[0]["location_path"][0]["name"] == "A1"
    r = await client.post(
        "/api/v1/stock/remove", json={"item_id": item["id"], "location_id": loc["id"], "quantity": 9}
    )
    assert r.status_code == 400 and "Only 3" in r.json()["message"]
    low = (await client.get("/api/v1/stock/low")).json()
    assert low[0]["item_id"] == item["id"]
    moves = (await client.get(f"/api/v1/movements?item_id={item['id']}")).json()
    r = await client.post(f"/api/v1/movements/{moves[0]['id']}/undo")
    assert r.status_code == 200 and r.json()["reason"] == "undo"
    r = await client.post(
        "/api/v1/stock/adjust", json={"item_id": item["id"], "location_id": loc["id"], "counted": 0}
    )
    assert r.status_code == 200 and r.json() is None


async def test_unit_actions_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Cells", "tracking_mode": "unit"})).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "30Q"})).json()
    loc = (await client.post("/api/v1/locations", json={"name": "Box"})).json()
    unit = (await client.post("/api/v1/units", json={"item_id": item["id"], "location_id": loc["id"]})).json()
    r = await client.post(f"/api/v1/units/{unit['id']}/check-out")
    assert r.json()["status"] == "checked_out"
    r = await client.post(f"/api/v1/units/{unit['id']}/check-in", json={})
    assert r.json()["status"] == "in_stock"
    r = await client.patch(f"/api/v1/units/{unit['id']}/condition", json={"condition": "tested_good"})
    assert r.json()["condition"] == "tested_good"
    other = (await client.post("/api/v1/locations", json={"name": "Shelf"})).json()
    r = await client.post(f"/api/v1/units/{unit['id']}/move", json={"location_id": other["id"]})
    assert r.json()["location_id"] == other["id"]
    r = await client.post(f"/api/v1/units/{unit['id']}/consume")
    assert r.json()["status"] == "consumed"
    assert (await client.post(f"/api/v1/units/{unit['id']}/dispose")).status_code == 400


async def test_low_stock_uses_constant_queries(db):
    from sqlalchemy import event

    cat = await make_category(db, "Screws")
    loc = await make_location(db, "A1")
    for i in range(20):
        item = await make_item(db, cat, f"S{i}", min_stock=10)
        if i:
            await stock.add_stock(db, item.id, loc.id, i)
    statements = []
    sync_engine = db.bind.sync_engine if hasattr(db.bind, "sync_engine") else db.bind.engine.sync_engine
    listener = lambda *a, **k: statements.append(1)  # noqa: E731
    event.listen(sync_engine, "before_cursor_execute", listener)
    try:
        rows = await stock.low_stock(db)
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)
    assert len(rows) == 10 and rows[0].on_hand == 0
    assert len(statements) <= 3
