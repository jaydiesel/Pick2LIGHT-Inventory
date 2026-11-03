import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from pick2light.core import attachments as att_svc
from pick2light.core import trash
from pick2light.core.attachments import list_attachments, save_upload
from pick2light.core.barcodes import lookup_barcode, register_barcode
from pick2light.core.categories import (
    FieldDefIn,
    LogEntryTypeIn,
    add_field,
    create_log_type,
    delete_category,
    delete_log_type,
)
from pick2light.core.items import delete_item
from pick2light.core.locations import delete_location
from pick2light.core.logs import LogEntryIn, add_log_entry
from pick2light.core.stock import add_stock
from pick2light.core.units import delete_unit
from pick2light.errors import Conflict
from pick2light.models import (
    Attachment,
    Barcode,
    Category,
    Item,
    Location,
    LogEntry,
    LogEntryType,
    StockMovement,
    Unit,
)
from tests.factories import make_category, make_item, make_location, make_unit


def _long_ago(days: int = 31) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _age(db, model, row_id: int, days: int = 31) -> None:
    await db.execute(update(model).where(model.id == row_id).values(deleted_at=_long_ago(days)))


async def _log_type(db, category, key="test", applies_to="unit"):
    return await create_log_type(
        db,
        category.id,
        LogEntryTypeIn.model_validate(
            {
                "key": key,
                "name": key.title(),
                "applies_to": applies_to,
                "fields": [{"key": "v", "label": "V", "type": "number"}],
            }
        ),
    )


async def test_deleted_item_listed_and_restored(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "Gone", sku="GONE-1")
    await delete_item(db, item.id)
    entries = await trash.list_trash(db)
    assert [(e.type, e.id, e.name) for e in entries] == [("item", item.id, "Gone")]
    assert entries[0].deleted_at is not None
    assert await lookup_barcode(db, "GONE-1") is None

    await trash.restore(db, "item", item.id)
    assert await trash.list_trash(db) == []
    found = await lookup_barcode(db, "GONE-1")
    assert (found.target_type, found.target_id, found.kind) == ("item", item.id, "sku")


async def test_deleted_item_barcode_not_found(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "Gone", sku="GONE-2")
    await register_barcode(db, "5012345678900", "item", item.id, "manufacturer")
    await delete_item(db, item.id)
    assert await lookup_barcode(db, "GONE-2") is None
    assert await lookup_barcode(db, "5012345678900") is None  # kept, but hidden
    assert await lookup_barcode(db, "gone-2") is None  # also on the case-insensitive path


async def test_custom_codes_survive_delete_and_work_after_restore(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="SN-7")
    loc = await make_location(db, "Shelf")
    await register_barcode(db, "ITEM-EAN", "item", item.id, "manufacturer")
    await register_barcode(db, "UNIT-CUSTOM", "unit", unit.id, "custom")
    await register_barcode(db, "LOC-CUSTOM", "location", loc.id, "custom")
    await delete_unit(db, unit.id)
    await delete_item(db, item.id)
    await delete_location(db, loc.id)

    kinds = set(await db.scalars(select(Barcode.kind)))
    assert kinds == {"manufacturer", "custom"}  # automatic codes and the serial are gone
    for code in ("ITEM-EAN", "UNIT-CUSTOM", "LOC-CUSTOM", "SN-7", unit.unit_code, loc.code):
        assert await lookup_barcode(db, code) is None

    await trash.restore(db, "item", item.id)
    await trash.restore(db, "unit", unit.id)
    await trash.restore(db, "location", loc.id)
    for code, target in (
        ("ITEM-EAN", item.id),
        ("UNIT-CUSTOM", unit.id),
        ("LOC-CUSTOM", loc.id),
        ("SN-7", unit.id),
        (unit.unit_code, unit.id),
        (loc.code, loc.id),
    ):
        assert (await lookup_barcode(db, code)).target_id == target


async def test_restore_refuses_when_automatic_code_was_taken(db):
    category = await make_category(db, "Misc")
    item = await make_item(db, category, "Gone", sku="TAKEN-1")
    other = await make_item(db, category, "Other")
    await delete_item(db, item.id)
    await register_barcode(db, "TAKEN-1", "item", other.id, "custom")
    with pytest.raises(Conflict, match="TAKEN-1"):
        await trash.restore(db, "item", item.id)
    assert (await db.get(Item, item.id)).deleted_at is not None


async def test_restore_unit_serial_taken_leaves_nothing_half_restored(db):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="SN-1")
    other = await make_unit(db, item)
    await delete_unit(db, unit.id)
    await register_barcode(db, "SN-1", "unit", other.id, "custom")
    with pytest.raises(Conflict, match="SN-1"):
        await trash.restore(db, "unit", unit.id)
    assert await lookup_barcode(db, unit.unit_code) is None
    assert (await db.get(Unit, unit.id)).deleted_at is not None


async def test_restore_child_of_deleted_parent_refused(db):
    parent = await make_location(db, "Cabinet")
    child = await make_location(db, "Drawer", parent=parent)
    await delete_location(db, child.id)
    await delete_location(db, parent.id)
    with pytest.raises(Conflict, match="Restore 'Cabinet' first"):
        await trash.restore(db, "location", child.id)
    await trash.restore(db, "location", parent.id)
    await trash.restore(db, "location", child.id)
    assert await trash.list_trash(db) == []


async def test_restore_refuses_deleted_category_item_unit_and_default_location(db):
    category = await make_category(db, "Parts")
    item = await make_item(db, category, "Resistor")
    lt = await _log_type(db, category)
    await delete_log_type(db, lt.id)
    await delete_item(db, item.id)
    await delete_category(db, category.id)
    with pytest.raises(Conflict, match="Restore 'Parts' first"):
        await trash.restore(db, "item", item.id)
    with pytest.raises(Conflict, match="Restore 'Parts' first"):
        await trash.restore(db, "log_entry_type", lt.id)

    cells = await make_category(db, "Cells", tracking_mode="unit")
    shelf = await make_location(db, "Shelf")
    cell_item = await make_item(db, cells, "18650", default_location_id=shelf.id)
    unit = await make_unit(db, cell_item)
    await delete_unit(db, unit.id)
    # unit whose item is in the trash (consumed, so the item may be deleted)
    await db.execute(
        text("UPDATE unit SET status = 'consumed', location_id = NULL WHERE id = :i"),
        {"i": unit.id},
    )
    await delete_item(db, cell_item.id)
    with pytest.raises(Conflict, match="Restore '18650' first"):
        await trash.restore(db, "unit", unit.id)
    # item whose default location is in the trash
    await delete_location(db, shelf.id)
    with pytest.raises(Conflict, match="Restore 'Shelf' first"):
        await trash.restore(db, "item", cell_item.id)


async def test_restore_category_checks_parent_and_key_collisions(db):
    root = await make_category(db, "Root", fields=[{"key": "color", "type": "text"}])
    child = await make_category(db, "Child", parent=root, fields=[{"key": "size", "type": "text"}])
    await _log_type(db, child, key="inspect")
    await delete_category(db, child.id)
    await delete_category(db, root.id)
    with pytest.raises(Conflict, match="Restore 'Root' first"):
        await trash.restore(db, "category", child.id)
    await trash.restore(db, "category", root.id)

    await add_field(
        db, root.id, FieldDefIn.model_validate({"key": "size", "label": "S", "type": "text"})
    )
    with pytest.raises(Conflict, match="size"):
        await trash.restore(db, "category", child.id)
    await db.execute(
        text("DELETE FROM field_definition WHERE key = 'size' AND category_id = :c"), {"c": root.id}
    )

    await _log_type(db, root, key="inspect")
    with pytest.raises(Conflict, match="inspect"):
        await trash.restore(db, "category", child.id)
    await db.execute(text("DELETE FROM log_entry_type WHERE category_id = :c"), {"c": root.id})

    await trash.restore(db, "category", child.id)
    assert (await db.get(Category, child.id)).deleted_at is None


async def test_restore_log_type_key_collision_refused(db):
    root = await make_category(db, "Root")
    child = await make_category(db, "Child", parent=root, tracking_mode="unit")
    first = await _log_type(db, child, key="capacity")
    await delete_log_type(db, first.id)
    await _log_type(db, root, key="capacity")
    with pytest.raises(Conflict, match="capacity"):
        await trash.restore(db, "log_entry_type", first.id)


async def test_restore_unknown_or_live_row_not_found(db):
    from pick2light.errors import NotFound

    category = await make_category(db, "Misc")
    with pytest.raises(NotFound):
        await trash.restore(db, "category", category.id)  # alive, not in the trash
    with pytest.raises(NotFound):
        await trash.restore(db, "item", 99999)


async def test_list_trash_newest_first_all_types(db):
    category = await make_category(db, "Misc")
    loc = await make_location(db, "Shelf")
    item = await make_item(db, category, "Thing")
    lt = await _log_type(db, category)
    await delete_item(db, item.id)
    await delete_location(db, loc.id)
    await delete_log_type(db, lt.id)
    await _age(db, Item, item.id, 5)
    await _age(db, Location, loc.id, 3)
    await _age(db, LogEntryType, lt.id, 1)
    assert [e.type for e in await trash.list_trash(db)] == ["log_entry_type", "location", "item"]


# --------------------------------------------------------------------------- purge


async def test_purge_expired_only_old_rows(db, tmp_path):
    category = await make_category(db, "Misc")
    old = await make_item(db, category, "Old")
    recent = await make_item(db, category, "Recent")
    old_loc = await make_location(db, "OldLoc")
    await delete_item(db, old.id)
    await delete_item(db, recent.id)
    await delete_location(db, old_loc.id)
    await _age(db, Item, old.id, 31)
    await _age(db, Item, recent.id, 1)
    await _age(db, Location, old_loc.id, 40)

    assert await trash.purge_expired(db, 30, root=tmp_path) == 2
    assert await db.get(Item, old.id) is None
    assert await db.get(Location, old_loc.id) is None
    assert (await db.get(Item, recent.id)).deleted_at is not None
    assert [e.id for e in await trash.list_trash(db)] == [recent.id]
    assert (
        await db.scalar(
            select(func.count()).select_from(Barcode).where(Barcode.target_id == old.id)
        )
    ) == 0


async def test_purge_keeps_movements_with_null_item(db, tmp_path):
    category = await make_category(db, "Misc")
    shelf = await make_location(db, "Shelf")
    item = await make_item(db, category, "Bulk")
    await add_stock(db, item.id, shelf.id, 5)
    await db.execute(text("UPDATE stock SET quantity = 0"))
    movements_before = await db.scalar(select(func.count()).select_from(StockMovement))
    await delete_item(db, item.id)
    await delete_location(db, shelf.id)
    await _age(db, Item, item.id)
    await _age(db, Location, shelf.id)
    await trash.purge_expired(db, 30, root=tmp_path)
    rows = (await db.execute(select(StockMovement))).scalars().all()
    assert len(rows) == movements_before >= 1
    assert all(m.item_id is None and m.to_location_id is None for m in rows)
    assert await db.scalar(text("SELECT count(*) FROM stock")) == 0


async def test_purge_unit_removes_its_logs_barcodes_and_keeps_movements(db, tmp_path):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item, serial_number="SN-5")
    keeper = await make_unit(db, item)
    lt = await _log_type(db, cells)
    await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"v": 1}))
    await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=keeper.id, values={"v": 2}))
    await register_barcode(db, "UNIT-CUSTOM", "unit", unit.id, "custom")
    await delete_unit(db, unit.id)
    await _age(db, Unit, unit.id)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 1
    assert await db.get(Unit, unit.id) is None
    assert await db.scalar(select(func.count()).select_from(LogEntry)) == 1
    assert await lookup_barcode(db, "UNIT-CUSTOM") is None
    assert (
        await db.scalar(
            select(func.count()).select_from(Barcode).where(Barcode.code == "UNIT-CUSTOM")
        )
        == 0
    )
    assert (
        await db.scalar(
            select(func.count()).select_from(StockMovement).where(StockMovement.item_id == item.id)
        )
    ) == 2
    assert (
        await db.scalar(
            select(func.count()).select_from(StockMovement).where(StockMovement.unit_id.is_(None))
        )
        == 1
    )


async def test_purge_skips_log_type_that_still_has_entries(db, tmp_path):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    kept = await _log_type(db, cells, key="kept")
    empty = await _log_type(db, cells, key="empty")
    await add_log_entry(db, LogEntryIn(log_entry_type_id=kept.id, unit_id=unit.id, values={"v": 1}))
    for lt in (kept, empty):
        await delete_log_type(db, lt.id)
        await _age(db, LogEntryType, lt.id)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 1
    assert await db.get(LogEntryType, empty.id) is None
    assert await db.get(LogEntryType, kept.id) is not None
    assert await db.scalar(select(func.count()).select_from(LogEntry)) == 1
    await trash.restore(db, "log_entry_type", kept.id)  # still restorable


async def test_purge_item_skips_while_units_remain_and_purges_dependents(db, tmp_path):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    await db.execute(
        text("UPDATE unit SET status = 'consumed', location_id = NULL WHERE id = :i"),
        {"i": unit.id},
    )
    await delete_item(db, item.id)
    await _age(db, Item, item.id)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 0
    assert await db.get(Item, item.id) is not None
    await db.execute(text("UPDATE unit SET deleted_at = now() - interval '40 days'"))
    assert await trash.purge_expired(db, 30, root=tmp_path) == 2
    assert await db.get(Item, item.id) is None


async def test_purge_category_waits_for_children_items_and_log_entries(db, tmp_path):
    root = await make_category(db, "Root", fields=[{"key": "color", "type": "text"}])
    child = await make_category(db, "Child", parent=root)
    await _log_type(db, child, key="note", applies_to="item")
    await delete_category(db, child.id)
    await delete_category(db, root.id)
    await _age(db, Category, child.id)
    await _age(db, Category, root.id)
    assert await trash.purge_expired(db, 30, root=tmp_path) == 2  # child first, then root
    assert await db.scalar(select(func.count()).select_from(Category)) == 0
    assert await db.scalar(text("SELECT count(*) FROM field_definition")) == 0
    assert await db.scalar(select(func.count()).select_from(LogEntryType)) == 0


async def test_purge_category_with_item_in_trash_is_kept(db, tmp_path):
    category = await make_category(db, "Parts")
    item = await make_item(db, category, "R")
    await delete_item(db, item.id)
    await delete_category(db, category.id)
    await _age(db, Category, category.id)  # category old, item recent
    assert await trash.purge_expired(db, 30, root=tmp_path) == 0
    assert await db.get(Category, category.id) is not None


async def test_purge_removes_attachments_and_files_after_commit(committed_db, settings):
    root = settings.data_dir / "attachments"
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256))

    async def chunks():
        yield png

    async with committed_db() as s:
        category = await make_category(s, "Misc")
        item = await make_item(s, category, "Gone")
        att = await save_upload(
            s,
            owner_type="item",
            owner_id=item.id,
            kind="photo",
            filename="p.png",
            content_type="image/png",
            stream=chunks(),
            root=root,
        )
        path = att_svc.attachment_path(att, root=root)
        await delete_item(s, item.id)
        await _age(s, Item, item.id)
        item_id = item.id
        await s.commit()
    assert path.exists()
    async with committed_db() as s:
        assert await trash.purge_expired(s, 30, root=root) == 1
        assert path.exists()  # file removal waits for the commit
        await s.commit()
    await att_svc.finish_pending_unlinks()
    assert not path.exists()
    async with committed_db() as s:
        assert await list_attachments(s, "item", item_id) == []
        assert await s.scalar(select(func.count()).select_from(Attachment)) == 0


async def test_purge_loop_survives_errors(monkeypatch, committed_db, tmp_path):
    calls = []

    async def flaky(db, retention_days, *, root):
        calls.append(retention_days)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(trash, "purge_expired", flaky)
    task = asyncio.create_task(trash.purge_loop(committed_db, tmp_path, interval=0.01))
    for _ in range(100):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 3 and set(calls) == {30}


async def test_lifespan_purges_on_start_and_finishes_unlinks_on_stop(
    committed_db, settings, monkeypatch
):
    from pick2light.app import create_app

    async with committed_db() as s:
        category = await make_category(s, "Misc")
        item = await make_item(s, category, "Gone")
        await delete_item(s, item.id)
        await _age(s, Item, item.id)
        item_id = item.id
        await s.commit()
    finished = []
    real = att_svc.finish_pending_unlinks

    async def spy():
        finished.append(True)
        await real()

    monkeypatch.setattr(att_svc, "finish_pending_unlinks", spy)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        for _ in range(100):
            async with committed_db() as s:
                if await s.get(Item, item_id) is None:
                    break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("start-up purge did not run")
    assert finished


# --------------------------------------------------------------------------- API


async def test_api_trash_list_and_restore(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    item = (
        await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Gone"})
    ).json()
    assert (await client.delete(f"/api/v1/items/{item['id']}")).status_code == 204
    listed = (await client.get("/api/v1/trash")).json()
    assert [(e["type"], e["id"], e["name"]) for e in listed] == [("item", item["id"], "Gone")]
    assert (await client.get(f"/api/v1/barcodes/{item['sku']}")).status_code == 404
    r = await client.post(f"/api/v1/trash/item/{item['id']}/restore")
    assert r.status_code == 204
    assert (await client.get("/api/v1/trash")).json() == []
    assert (await client.get(f"/api/v1/barcodes/{item['sku']}")).status_code == 200


async def test_api_restore_errors(client):
    assert (await client.post("/api/v1/trash/item/999/restore")).status_code == 404
    assert (await client.post("/api/v1/trash/widget/1/restore")).status_code == 422
    parent = (await client.post("/api/v1/locations", json={"name": "Cabinet"})).json()
    child = (
        await client.post("/api/v1/locations", json={"name": "Drawer", "parent_id": parent["id"]})
    ).json()
    await client.delete(f"/api/v1/locations/{child['id']}")
    await client.delete(f"/api/v1/locations/{parent['id']}")
    r = await client.post(f"/api/v1/trash/location/{child['id']}/restore")
    assert r.status_code == 409 and "Restore 'Cabinet' first" in r.json()["message"]


async def test_undo_of_purged_item_movement_refused(db, tmp_path):
    from pick2light.core.stock import undo_movement

    category = await make_category(db, "Misc")
    shelf = await make_location(db, "Shelf")
    item = await make_item(db, category, "Bulk")
    movement = await add_stock(db, item.id, shelf.id, 5)
    await db.execute(text("UPDATE stock SET quantity = 0"))
    await delete_item(db, item.id)
    await _age(db, Item, item.id)
    await trash.purge_expired(db, 30, root=tmp_path)
    with pytest.raises(Conflict, match="permanently deleted"):
        await undo_movement(db, movement.id)


async def test_undo_after_unit_purge_refused(db, tmp_path):
    from pick2light.core.stock import move_unit, undo_movement

    cells = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cells, "18650")
    a = await make_location(db, "A")
    b = await make_location(db, "B")
    unit = await make_unit(db, item, location_id=a.id)
    movement = await move_unit(db, unit.id, b.id)
    await delete_unit(db, unit.id)
    await _age(db, Unit, unit.id)
    await trash.purge_expired(db, 30, root=tmp_path)
    with pytest.raises(Conflict, match="permanently deleted"):
        await undo_movement(db, movement.id)
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == 2


async def test_undo_after_location_purge_refused(db, tmp_path):
    from pick2light.core.stock import move_stock, undo_movement

    category = await make_category(db, "Misc")
    a = await make_location(db, "A")
    b = await make_location(db, "B")
    item = await make_item(db, category, "Bulk")
    await add_stock(db, item.id, a.id, 5)
    movement = await move_stock(db, item.id, a.id, b.id, 5)
    await delete_location(db, a.id)
    await _age(db, Location, a.id)
    await trash.purge_expired(db, 30, root=tmp_path)
    with pytest.raises(Conflict, match="permanently deleted"):
        await undo_movement(db, movement.id)
    quantity = await db.scalar(
        text("SELECT quantity FROM stock WHERE location_id = :b"), {"b": b.id}
    )
    assert quantity == 5  # nothing was removed
