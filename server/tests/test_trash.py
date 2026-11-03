from datetime import UTC, datetime, timedelta

import pytest
from factories import make_category, make_item, make_location, make_unit
from sqlalchemy import select, update

from pick2light.core import stock, trash
from pick2light.core.barcodes import lookup_barcode
from pick2light.core.categories import delete_category
from pick2light.core.items import delete_item
from pick2light.core.locations import delete_location
from pick2light.core.units import delete_unit
from pick2light.errors import Conflict
from pick2light.models import Item, StockMovement, Unit


async def test_deleted_item_listed_and_restored(db):
    item = await make_item(db, await make_category(db, "Screws"), "M3")
    await delete_item(db, item.id)
    entries = await trash.list_trash(db)
    assert [(e.type, e.id, e.name) for e in entries] == [("item", item.id, "M3")]
    await trash.restore(db, "item", item.id)
    assert await trash.list_trash(db) == []
    assert (await lookup_barcode(db, item.sku)).target_id == item.id


async def test_deleted_item_barcode_not_found(db):
    item = await make_item(db, await make_category(db, "Screws"), "M3")
    await delete_item(db, item.id)
    assert await lookup_barcode(db, item.sku) is None


async def test_restore_unit_reregisters_codes(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    unit = await make_unit(db, await make_item(db, cat, "30Q"), serial_number="SN1")
    await delete_unit(db, unit.id)
    await trash.restore(db, "unit", unit.id)
    assert (await lookup_barcode(db, unit.unit_code)).target_id == unit.id
    assert (await lookup_barcode(db, "SN1")).target_id == unit.id


async def test_restore_child_of_deleted_parent_refused(db):
    garage = await make_location(db, "Garage")
    box = await make_location(db, "Box", parent=garage)
    await delete_location(db, box.id)
    await delete_location(db, garage.id)
    with pytest.raises(Conflict, match="Garage"):
        await trash.restore(db, "location", box.id)
    await trash.restore(db, "location", garage.id)
    await trash.restore(db, "location", box.id)


async def test_restore_item_in_deleted_category_refused(db):
    cat = await make_category(db, "Screws")
    item = await make_item(db, cat, "M3")
    await delete_item(db, item.id)
    await delete_category(db, cat.id)
    with pytest.raises(Conflict):
        await trash.restore(db, "item", item.id)


async def test_restore_item_sku_taken_refused(db):
    cat = await make_category(db, "Screws")
    item = await make_item(db, cat, "M3", sku="ABC")
    await delete_item(db, item.id)
    from pick2light.core.barcodes import register_barcode

    loc = await make_location(db, "L")
    await register_barcode(db, "ABC", "location", loc.id, "custom")
    with pytest.raises(Conflict):
        await trash.restore(db, "item", item.id)


async def age(db, model, row_id, days):
    await db.execute(
        update(model).where(model.id == row_id).values(deleted_at=datetime.now(UTC) - timedelta(days=days))
    )


async def test_purge_expired_only_old_rows(db, tmp_path):
    cat = await make_category(db, "Screws")
    old = await make_item(db, cat, "Old")
    new = await make_item(db, cat, "New")
    await delete_item(db, old.id)
    await delete_item(db, new.id)
    await age(db, Item, old.id, 31)
    await age(db, Item, new.id, 1)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 1
    assert [e.id for e in await trash.list_trash(db)] == [new.id]


async def test_purge_keeps_movements_with_null_item(db, tmp_path):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cat, "30Q")
    loc = await make_location(db, "Box")
    unit = await make_unit(db, item, location_id=loc.id)
    await stock.consume_unit(db, unit.id)
    await delete_item(db, item.id)
    await age(db, Item, item.id, 40)
    await trash.purge_expired(db, 30, root=tmp_path)
    moves = list(await db.scalars(select(StockMovement)))
    assert len(moves) == 2 and all(m.item_id is None and m.unit_id is None for m in moves)
    assert await db.get(Unit, unit.id) is None


async def test_purge_location_and_category(db, tmp_path):
    from pick2light.models import Category, Location

    cat = await make_category(db, "Old cat")
    loc = await make_location(db, "Old loc")
    await delete_category(db, cat.id)
    await delete_location(db, loc.id)
    await age(db, Category, cat.id, 31)
    await age(db, Location, loc.id, 31)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 2


async def test_trash_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Thing"})).json()
    await client.delete(f"/api/v1/items/{item['id']}")
    listed = (await client.get("/api/v1/trash")).json()
    assert listed[0]["type"] == "item" and listed[0]["name"] == "Thing"
    r = await client.post(f"/api/v1/trash/item/{item['id']}/restore")
    assert r.status_code == 204
    assert (await client.get(f"/api/v1/items/{item['id']}")).status_code == 200


async def test_purge_keeps_log_type_that_has_history(db, tmp_path):
    from pick2light.core.categories import FieldDefIn, LogEntryTypeIn, create_log_type, delete_log_type
    from pick2light.core.logs import LogEntryIn, add_log_entry
    from pick2light.models import LogEntry, LogEntryType

    cat = await make_category(db, "Cells", tracking_mode="unit")
    lt = await create_log_type(
        db,
        cat.id,
        LogEntryTypeIn(
            key="capacity_test", name="Capacity Test", fields=[FieldDefIn(key="ir", type="number")]
        ),
    )
    unit = await make_unit(db, await make_item(db, cat, "30Q"))
    await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"ir": 22}))
    await delete_log_type(db, lt.id)
    await age(db, LogEntryType, lt.id, 60)
    await trash.purge_expired(db, 30, root=tmp_path)
    assert await db.get(LogEntryType, lt.id) is not None
    assert len(list(await db.scalars(select(LogEntry)))) == 1


async def test_restore_category_with_field_key_clash_refused(db):
    from pick2light.core.categories import FieldDefIn, add_field

    root = await make_category(db, "Electronics")
    res = await make_category(db, "Resistors", parent=root, fields=[{"key": "tolerance", "type": "text"}])
    await delete_category(db, res.id)
    await add_field(db, root.id, FieldDefIn(key="tolerance", type="text"))
    with pytest.raises(Conflict, match="tolerance"):
        await trash.restore(db, "category", res.id)


async def test_restore_log_type_checks_family_only(db):
    from pick2light.core.categories import LogEntryTypeIn, create_log_type, delete_log_type

    cells = await make_category(db, "Cells", tracking_mode="unit")
    drives = await make_category(db, "Drives", tracking_mode="unit")
    lt = await create_log_type(db, cells.id, LogEntryTypeIn(key="check", name="Check"))
    await delete_log_type(db, lt.id)
    await create_log_type(db, drives.id, LogEntryTypeIn(key="check", name="Check"))
    await trash.restore(db, "log_entry_type", lt.id)
