import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pick2light.core.items import on_hand as item_on_hand
from pick2light.core.locations import delete_location
from pick2light.core.stock import (
    add_stock,
    adjust_stock,
    check_in_unit,
    check_out_unit,
    consume_unit,
    dispose_unit,
    item_stock,
    list_movements,
    low_stock,
    move_stock,
    move_unit,
    on_hand,
    remove_stock,
    set_condition,
    undo_movement,
)
from pick2light.core.units import get_unit
from pick2light.errors import Conflict, InvalidOperation, ValidationFailed
from pick2light.models import StockMovement
from tests.factories import make_category, make_item, make_location, make_unit


async def bulk_setup(db, qty=None):
    category = await make_category(db, "Resistors")
    item = await make_item(db, category, "10k")
    loc = await make_location(db, "Drawer A")
    if qty:
        await add_stock(db, item.id, loc.id, qty)
    return item, loc


async def unit_setup(db, **kw):
    category = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, category, "18650")
    loc = await make_location(db, "Shelf")
    unit = await make_unit(db, item, location_id=loc.id, **kw)
    return item, loc, unit


async def test_add_and_remove_bulk(db):
    item, loc = await bulk_setup(db)
    m = await add_stock(db, item.id, loc.id, 10)
    assert (m.reason, m.quantity_delta, m.to_location_id, m.from_location_id) == (
        "check_in",
        Decimal(10),
        loc.id,
        None,
    )
    assert m.source == "ui" and m.unit_id is None
    m = await remove_stock(db, item.id, loc.id, 4, note="project")
    assert (m.reason, m.quantity_delta, m.from_location_id, m.note) == (
        "check_out",
        Decimal(-4),
        loc.id,
        "project",
    )
    assert await on_hand(db, item.id) == 6
    assert await item_on_hand(db, item.id, "bulk") == 6
    consumed = await remove_stock(db, item.id, loc.id, 1, reason="consume", source="scan")
    assert (consumed.reason, consumed.source) == ("consume", "scan")
    rows = await item_stock(db, item.id)
    assert [(r.location_id, r.quantity) for r in rows] == [(loc.id, 5)]
    assert [p.name for p in rows[0].location_path] == ["Drawer A"]


async def test_quantities_validated(db):
    item, loc = await bulk_setup(db, 5)
    for bad in (0, -1):
        with pytest.raises(ValidationFailed):
            await add_stock(db, item.id, loc.id, bad)
        with pytest.raises(ValidationFailed):
            await remove_stock(db, item.id, loc.id, bad)
    with pytest.raises(ValidationFailed):
        await adjust_stock(db, item.id, loc.id, -1)
    with pytest.raises(InvalidOperation):
        await remove_stock(db, item.id, loc.id, 1, reason="check_in")


async def test_remove_more_than_present_refused(db):
    item, loc = await bulk_setup(db, 3)
    with pytest.raises(InvalidOperation) as exc:
        await remove_stock(db, item.id, loc.id, 4)
    assert "Only 3" in exc.value.message and "Drawer A" in exc.value.message
    assert await on_hand(db, item.id) == 3
    elsewhere = await make_location(db, "Elsewhere")
    with pytest.raises(InvalidOperation) as exc:
        await remove_stock(db, item.id, elsewhere.id, 1)
    assert "Only 0" in exc.value.message


async def test_move_stock(db):
    item, loc = await bulk_setup(db, 10)
    other = await make_location(db, "Drawer B")
    m = await move_stock(db, item.id, loc.id, other.id, 4)
    assert (m.reason, m.quantity_delta, m.from_location_id, m.to_location_id) == (
        "move",
        Decimal(4),
        loc.id,
        other.id,
    )
    assert {r.location_id: r.quantity for r in await item_stock(db, item.id)} == {
        loc.id: 6,
        other.id: 4,
    }
    assert await on_hand(db, item.id) == 10
    with pytest.raises(InvalidOperation) as exc:
        await move_stock(db, item.id, loc.id, other.id, 7)
    assert "Only 6" in exc.value.message
    with pytest.raises(InvalidOperation):
        await move_stock(db, item.id, loc.id, loc.id, 1)


async def test_zero_rows_kept_but_hidden(db):
    item, loc = await bulk_setup(db, 2)
    await remove_stock(db, item.id, loc.id, 2)
    assert await item_stock(db, item.id) == []
    assert await on_hand(db, item.id) == 0


async def test_adjust_writes_delta(db):
    item, loc = await bulk_setup(db, 10)
    m = await adjust_stock(db, item.id, loc.id, 7)
    assert m is not None
    assert (m.reason, m.quantity_delta, m.from_location_id, m.to_location_id) == (
        "adjust",
        Decimal(-3),
        loc.id,
        None,
    )
    assert await on_hand(db, item.id) == 7
    up = await adjust_stock(db, item.id, loc.id, 9)
    assert up is not None and (up.quantity_delta, up.to_location_id) == (Decimal(2), loc.id)
    assert await adjust_stock(db, item.id, loc.id, 9) is None
    assert await adjust_stock(db, item.id, loc.id, 0) is not None
    assert await on_hand(db, item.id) == 0


async def test_bulk_op_on_unit_item_refused(db):
    item, loc, _ = await unit_setup(db)
    for call in (
        add_stock(db, item.id, loc.id, 1),
        remove_stock(db, item.id, loc.id, 1),
        adjust_stock(db, item.id, loc.id, 1),
    ):
        with pytest.raises(InvalidOperation):
            await call


async def test_unit_op_on_missing_unit(db):
    from pick2light.errors import NotFound

    with pytest.raises(NotFound):
        await check_out_unit(db, 99999)


UNIT_CASES = [
    # (steps, expected final (status, location kept?)); an exception class means the last step fails
    (["check_out"], ("checked_out", True)),
    (["check_out", "check_in"], ("in_stock", True)),
    (["check_out", "consume"], ("consumed", False)),
    (["consume"], ("consumed", False)),
    (["dispose"], ("disposed", False)),
    (["check_out", "dispose"], ("disposed", False)),
    (["move"], ("in_stock", True)),
    (["check_in"], InvalidOperation),
    (["check_out", "check_out"], InvalidOperation),
    (["check_out", "move"], InvalidOperation),
    (["consume", "check_out"], InvalidOperation),
    (["consume", "consume"], InvalidOperation),
    (["dispose", "check_in"], InvalidOperation),
    (["dispose", "move"], InvalidOperation),
]


@pytest.mark.parametrize(("steps", "expected"), UNIT_CASES)
async def test_unit_transitions(db, steps, expected):
    _, loc, unit = await unit_setup(db)
    other = await make_location(db, "Other")
    ops = {
        "check_out": lambda: check_out_unit(db, unit.id),
        "check_in": lambda: check_in_unit(db, unit.id),
        "consume": lambda: consume_unit(db, unit.id),
        "dispose": lambda: dispose_unit(db, unit.id),
        "move": lambda: move_unit(db, unit.id, other.id),
    }
    for step in steps[:-1]:
        await ops[step]()
    if isinstance(expected, type):
        with pytest.raises(expected):
            await ops[steps[-1]]()
        return
    await ops[steps[-1]]()
    status, keeps_location = expected
    fresh = await get_unit(db, unit.id)
    assert fresh.status == status
    assert (fresh.location_id is not None) == keeps_location


async def test_unit_movements_recorded(db):
    item, loc, unit = await unit_setup(db)
    other = await make_location(db, "Bench")
    create = (await list_movements(db, unit_id=unit.id))[0]
    assert (create.reason, create.quantity_delta, create.to_location_id) == ("create", 1, loc.id)
    out = await check_out_unit(db, unit.id)
    assert (out.reason, out.quantity_delta, out.from_location_id, out.unit_id) == (
        "check_out",
        Decimal(-1),
        loc.id,
        unit.id,
    )
    back = await check_in_unit(db, unit.id, other.id)
    assert (back.reason, back.quantity_delta, back.to_location_id) == (
        "check_in",
        Decimal(1),
        other.id,
    )
    assert (await get_unit(db, unit.id)).location_id == other.id
    moved = await move_unit(db, unit.id, loc.id)
    assert (moved.reason, moved.quantity_delta, moved.from_location_id, moved.to_location_id) == (
        "move",
        Decimal(0),
        other.id,
        loc.id,
    )
    gone = await dispose_unit(db, unit.id)
    assert (gone.reason, gone.note, gone.quantity_delta) == ("consume", "disposed", Decimal(-1))
    assert await on_hand(db, item.id) == 0


async def test_check_in_without_any_location_refused(db):
    category = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, category, "18650")
    unit = await make_unit(db, item)  # no location
    await check_out_unit(db, unit.id)
    with pytest.raises(InvalidOperation):
        await check_in_unit(db, unit.id)
    shelf = await make_location(db, "Shelf")
    await check_in_unit(db, unit.id, shelf.id)
    assert (await get_unit(db, unit.id)).location_id == shelf.id


async def test_set_condition_writes_no_movement(db):
    _, _, unit = await unit_setup(db)
    before = await db.scalar(select(func.count()).select_from(StockMovement))
    updated = await set_condition(db, unit.id, "faulty")
    assert updated.condition == "faulty"
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == before
    with pytest.raises(ValidationFailed):
        await set_condition(db, unit.id, "shiny")


async def test_undo_bulk_add(db):
    item, loc = await bulk_setup(db, 5)
    added = await add_stock(db, item.id, loc.id, 3)
    undo = await undo_movement(db, added.id)
    assert (undo.reason, undo.reverses_movement_id, undo.quantity_delta) == (
        "undo",
        added.id,
        Decimal(-3),
    )
    assert await on_hand(db, item.id) == 5
    rows = {m.id: m for m in await list_movements(db, item_id=item.id)}
    assert rows[added.id].reversed is True
    assert rows[undo.id].reversed is False


async def test_undo_remove_move_and_adjust(db):
    item, loc = await bulk_setup(db, 10)
    other = await make_location(db, "Drawer B")
    removed = await remove_stock(db, item.id, loc.id, 4)
    await undo_movement(db, removed.id)
    assert await on_hand(db, item.id) == 10
    moved = await move_stock(db, item.id, loc.id, other.id, 6)
    await undo_movement(db, moved.id)
    assert {r.location_id: r.quantity for r in await item_stock(db, item.id)} == {loc.id: 10}
    adjusted = await adjust_stock(db, item.id, loc.id, 7)
    assert adjusted is not None
    await undo_movement(db, adjusted.id)
    assert await on_hand(db, item.id) == 10


async def test_undo_twice_refused(db):
    item, loc = await bulk_setup(db, 5)
    added = await add_stock(db, item.id, loc.id, 3)
    undo = await undo_movement(db, added.id)
    with pytest.raises(Conflict):
        await undo_movement(db, added.id)
    with pytest.raises(Conflict):
        await undo_movement(db, undo.id)  # undo movements cannot be undone
    assert await on_hand(db, item.id) == 5


async def test_undo_after_consumed_refused(db):
    item, loc = await bulk_setup(db)
    added = await add_stock(db, item.id, loc.id, 5)
    await remove_stock(db, item.id, loc.id, 4, reason="consume")
    with pytest.raises(InvalidOperation) as exc:
        await undo_movement(db, added.id)
    assert "Only 1" in exc.value.message
    assert await on_hand(db, item.id) == 1


async def test_undo_unit_movements(db):
    _, loc, unit = await unit_setup(db)
    other = await make_location(db, "Bench")
    out = await check_out_unit(db, unit.id)
    await undo_movement(db, out.id)
    assert (await get_unit(db, unit.id)).status == "in_stock"
    moved = await move_unit(db, unit.id, other.id)
    await undo_movement(db, moved.id)
    assert (await get_unit(db, unit.id)).location_id == loc.id
    await check_out_unit(db, unit.id)
    back = await check_in_unit(db, unit.id, other.id)
    await undo_movement(db, back.id)
    fresh = await get_unit(db, unit.id)
    assert (fresh.status, fresh.location_id) == ("checked_out", loc.id)
    await check_in_unit(db, unit.id)
    gone = await consume_unit(db, unit.id)
    await undo_movement(db, gone.id)
    fresh = await get_unit(db, unit.id)
    assert (fresh.status, fresh.location_id) == ("in_stock", loc.id)


async def test_undo_unit_refused_when_state_changed(db):
    _, _, unit = await unit_setup(db)
    out = await check_out_unit(db, unit.id)
    await consume_unit(db, unit.id)
    with pytest.raises(InvalidOperation):
        await undo_movement(db, out.id)


async def test_undo_create_refused(db):
    _, _, unit = await unit_setup(db)
    create = (await list_movements(db, unit_id=unit.id))[0]
    with pytest.raises(Conflict):
        await undo_movement(db, create.id)


async def test_low_stock_list(db):
    category = await make_category(db, "Resistors")
    low = await make_item(db, category, "Low", min_stock=5)
    fine = await make_item(db, category, "Fine", min_stock=2)
    await make_item(db, category, "NoMin")
    empty = await make_item(db, category, "Empty", min_stock=1)
    loc = await make_location(db)
    await add_stock(db, low.id, loc.id, 3)
    await add_stock(db, fine.id, loc.id, 2)
    cells = await make_category(db, "Cells", tracking_mode="unit")
    cell = await make_item(db, cells, "Cell", min_stock=2)
    await make_unit(db, cell, location_id=loc.id)
    rows = await low_stock(db)
    assert [(r.name, r.on_hand, r.min_stock) for r in rows] == [
        ("Cell", 1, 2),
        ("Empty", 0, 1),
        ("Low", 3, 5),
    ]
    assert (
        rows[2].item_id == low.id
        and rows[2].sku == low.sku
        and empty.id in {r.item_id for r in rows}
    )
    await add_stock(db, low.id, loc.id, 2)
    assert "Low" not in [r.name for r in await low_stock(db)]


async def test_list_movements_filters_and_paging(db):
    item, loc = await bulk_setup(db)
    for _ in range(3):
        await add_stock(db, item.id, loc.id, 1)
    other_item, other_loc = await bulk_setup(db)
    await add_stock(db, other_item.id, other_loc.id, 1)
    rows = await list_movements(db, item_id=item.id)
    assert len(rows) == 3 and rows[0].id > rows[1].id
    page = await list_movements(db, item_id=item.id, limit=2)
    assert len(page) == 2
    rest = await list_movements(db, item_id=item.id, before_id=page[-1].id)
    assert [r.id for r in rest] == [rows[2].id]


async def test_delete_location_with_stock_refused(db):
    item, loc = await bulk_setup(db, 2)
    with pytest.raises(Conflict):
        await delete_location(db, loc.id)
    await remove_stock(db, item.id, loc.id, 2)
    await delete_location(db, loc.id)  # zero rows no longer block


async def test_delete_location_with_units_refused(db):
    _, loc, unit = await unit_setup(db)
    with pytest.raises(Conflict):
        await delete_location(db, loc.id)
    await check_out_unit(db, unit.id)
    with pytest.raises(Conflict):  # checked-out units still call it home
        await delete_location(db, loc.id)
    await consume_unit(db, unit.id)
    await delete_location(db, loc.id)


async def test_concurrent_check_out_never_negative(committed_db):
    async with committed_db() as setup:
        category = await make_category(setup, "Resistors")
        item = await make_item(setup, category, "10k")
        loc = await make_location(setup, "Drawer")
        await add_stock(setup, item.id, loc.id, 5)
        await setup.commit()
        item_id, loc_id = item.id, loc.id

    started = asyncio.Event()

    async def check_out() -> None:
        async with committed_db() as session:  # its own connection and transaction
            await started.wait()
            await remove_stock(session, item_id, loc_id, 4)
            await asyncio.sleep(0.2)  # hold the row lock so the other request must wait
            await session.commit()

    tasks = [asyncio.ensure_future(check_out()) for _ in range(2)]
    await asyncio.sleep(0.1)
    started.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert sum(isinstance(r, InvalidOperation) for r in results) == 1
    assert sum(r is None for r in results) == 1
    async with committed_db() as fresh:
        assert await on_hand(fresh, item_id) == 1


async def test_api_stock_round_trip(client, db):
    item, loc = await bulk_setup(db)
    r = await client.post(
        "/api/v1/stock/add", json={"item_id": item.id, "location_id": loc.id, "quantity": 10}
    )
    assert r.status_code == 201
    added = r.json()
    assert (added["reason"], added["quantity_delta"], added["reversed"]) == ("check_in", 10, False)
    r = await client.post(
        "/api/v1/stock/remove", json={"item_id": item.id, "location_id": loc.id, "quantity": 20}
    )
    assert r.status_code == 400 and "Only 10" in r.json()["message"]
    r = await client.post(
        "/api/v1/stock/remove", json={"item_id": item.id, "location_id": loc.id, "quantity": 0}
    )
    assert r.status_code == 422
    r = await client.get(f"/api/v1/items/{item.id}/stock")
    assert [(s["quantity"], s["location_path"][0]["name"]) for s in r.json()] == [(10, "Drawer A")]
    r = await client.post(
        "/api/v1/stock/adjust", json={"item_id": item.id, "location_id": loc.id, "counted": 10}
    )
    assert r.json() == {"movement": None}
    r = await client.post(
        "/api/v1/stock/adjust", json={"item_id": item.id, "location_id": loc.id, "counted": 7}
    )
    assert r.json()["movement"]["quantity_delta"] == -3
    other = await make_location(db, "B")
    r = await client.post(
        "/api/v1/stock/move",
        json={
            "item_id": item.id,
            "from_location_id": loc.id,
            "to_location_id": other.id,
            "quantity": 2,
        },
    )
    assert r.status_code == 201
    moved_id = r.json()["id"]
    r = await client.post(f"/api/v1/movements/{moved_id}/undo")
    assert r.status_code == 201 and r.json()["reason"] == "undo"
    assert (await client.post(f"/api/v1/movements/{moved_id}/undo")).status_code == 409
    # the original add can no longer be undone: only 7 are left of the 10
    assert (await client.post(f"/api/v1/movements/{added['id']}/undo")).status_code == 400
    r = await client.get("/api/v1/movements", params={"item_id": item.id, "limit": 2})
    assert len(r.json()) == 2 and r.json()[0]["reason"] == "undo"
    r = await client.get("/api/v1/movements", params={"item_id": item.id, "limit": 500})
    assert r.status_code == 422


async def test_api_units_and_low_stock(client, db):
    item, loc, unit = await unit_setup(db)
    r = await client.post(f"/api/v1/units/{unit.id}/check-out")
    assert r.status_code == 201 and r.json()["reason"] == "check_out"
    assert (await client.post(f"/api/v1/units/{unit.id}/check-out")).status_code == 400
    r = await client.post(f"/api/v1/units/{unit.id}/check-in", json={"location_id": loc.id})
    assert r.status_code == 201
    other = await make_location(db, "Bench")
    r = await client.post(f"/api/v1/units/{unit.id}/move", json={"location_id": other.id})
    assert r.json()["quantity_delta"] == 0
    r = await client.patch(f"/api/v1/units/{unit.id}/condition", json={"condition": "faulty"})
    assert r.json()["condition"] == "faulty"
    assert (
        await client.patch(f"/api/v1/units/{unit.id}/condition", json={"condition": "x"})
    ).status_code == 422
    r = await client.post(f"/api/v1/units/{unit.id}/dispose")
    assert r.json()["note"] == "disposed"
    r = await client.get("/api/v1/movements", params={"unit_id": unit.id})
    assert [m["reason"] for m in r.json()][-1] == "create"
    await client.patch(f"/api/v1/items/{item.id}", json={"min_stock": 3})
    r = await client.get("/api/v1/stock/low")
    assert [(row["name"], row["on_hand"], row["min_stock"]) for row in r.json()] == [
        ("18650", 0, 3)
    ]
