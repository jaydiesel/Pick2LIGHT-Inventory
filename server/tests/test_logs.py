from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from pick2light.core.categories import LogEntryTypeIn, create_log_type, delete_log_type
from pick2light.core.logs import (
    LogEntryIn,
    LogEntryPatch,
    add_log_entry,
    delete_log_entry,
    latest_values,
    list_log_entries,
    update_log_entry,
)
from pick2light.errors import InvalidOperation, NotFound, ValidationFailed
from tests.factories import make_category, make_item, make_unit

CAPACITY_TEST = {
    "key": "capacity_test",
    "name": "Capacity Test",
    "applies_to": "unit",
    "fields": [
        {
            "key": "capacity_mah",
            "label": "Capacity",
            "type": "number",
            "number_unit": "mAh",
            "number_si_prefixes": False,
        },
        {"key": "ir_mohm", "label": "Internal resistance", "type": "number", "number_unit": "Ω"},
        {"key": "storage_v", "label": "Storage voltage", "type": "number", "number_unit": "V"},
    ],
    "summary_fields": ["capacity_mah", "ir_mohm"],
}


async def make_cell(db, parent_type=False):
    cells = await make_category(db, "Cells", tracking_mode="unit")
    holder = cells
    if parent_type:
        holder = cells
        cells = await make_category(db, "Li-ion", parent=holder)
    lt = await create_log_type(db, holder.id, LogEntryTypeIn.model_validate(CAPACITY_TEST))
    item = await make_item(db, cells, "18650")
    unit = await make_unit(db, item)
    return unit, lt


def when(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


async def test_add_capacity_test_entry(db):
    unit, lt = await make_cell(db)
    entry = await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id,
            unit_id=unit.id,
            values={"capacity_mah": 2950, "ir_mohm": "22", "storage_v": 3.7},
        ),
    )
    assert entry.values == {"capacity_mah": 2950, "ir_mohm": 22, "storage_v": 3.7}
    assert all(isinstance(v, int | float) for v in entry.values.values())
    rows = await list_log_entries(db, unit_id=unit.id)
    assert len(rows) == 1
    assert rows[0].values_display == {
        "capacity_mah": "2950mAh",
        "ir_mohm": "22Ω",
        "storage_v": "3.7V",
    }


async def test_latest_values_pick_newest_by_performed_at(db):
    unit, lt = await make_cell(db)
    for day, cap in (("2026-06-01", 2900), ("2026-01-01", 3000)):  # newest inserted first
        await add_log_entry(
            db,
            LogEntryIn(
                log_entry_type_id=lt.id,
                unit_id=unit.id,
                performed_at=when(day),
                values={"capacity_mah": cap},
            ),
        )
    latest = await latest_values(db, unit_id=unit.id)
    assert latest["capacity_test"].values == {"capacity_mah": 2900}
    assert latest["capacity_test"].performed_at == when("2026-06-01")
    rows = await list_log_entries(db, unit_id=unit.id)
    assert [r.values["capacity_mah"] for r in rows] == [2900, 3000]  # newest first
    # the SQL view agrees
    got = (
        await db.execute(
            text(
                "SELECT type_key, values->>'capacity_mah' FROM unit_latest_values "
                "WHERE unit_id = :u"
            ),
            {"u": unit.id},
        )
    ).all()
    assert got == [("capacity_test", "2900")]


async def test_latest_only_summary_fields(db):
    unit, lt = await make_cell(db)
    await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id,
            unit_id=unit.id,
            values={"capacity_mah": 2950, "ir_mohm": 22, "storage_v": 3.7},
        ),
    )
    latest = await latest_values(db, unit_id=unit.id)
    entry = latest["capacity_test"]
    assert set(entry.values) == {"capacity_mah", "ir_mohm"}
    assert set(entry.values_display) == {"capacity_mah", "ir_mohm"}


async def test_latest_skips_deleted_log_type(db):
    unit, lt = await make_cell(db)
    await add_log_entry(
        db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"capacity_mah": 1})
    )
    await delete_log_type(db, lt.id)
    assert await latest_values(db, unit_id=unit.id) == {}


async def test_wrong_category_type_refused(db):
    unit, _ = await make_cell(db)
    other = await make_category(db, "Other")
    other_type = await create_log_type(
        db,
        other.id,
        LogEntryTypeIn.model_validate({**CAPACITY_TEST, "key": "other_test"}),
    )
    with pytest.raises(InvalidOperation):
        await add_log_entry(
            db,
            LogEntryIn(
                log_entry_type_id=other_type.id, unit_id=unit.id, values={"capacity_mah": 1}
            ),
        )


async def test_applies_to_mismatch_refused(db):
    unit, lt = await make_cell(db)
    item_id = unit.item_id
    with pytest.raises(InvalidOperation):
        await add_log_entry(
            db, LogEntryIn(log_entry_type_id=lt.id, item_id=item_id, values={"capacity_mah": 1})
        )


async def test_inherited_log_type_allowed(db):
    unit, lt = await make_cell(db, parent_type=True)
    entry = await add_log_entry(
        db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"capacity_mah": 5})
    )
    assert entry.id


async def test_exactly_one_target(db):
    unit, lt = await make_cell(db)
    with pytest.raises(ValidationFailed):
        await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, values={}))
    with pytest.raises(ValidationFailed):
        await add_log_entry(
            db,
            LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, item_id=unit.item_id, values={}),
        )


async def test_invalid_values_refused(db):
    unit, lt = await make_cell(db)
    with pytest.raises(ValidationFailed):
        await add_log_entry(
            db,
            LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"capacity_mah": "lots"}),
        )


async def test_item_log_and_update_delete(db):
    cat = await make_category(db, "Gear")
    lt = await create_log_type(
        db,
        cat.id,
        LogEntryTypeIn.model_validate(
            {
                "key": "service",
                "name": "Service",
                "applies_to": "item",
                "fields": [{"key": "cost", "label": "Cost", "type": "number"}],
                "summary_fields": ["cost"],
            }
        ),
    )
    item = await make_item(db, cat, "Drill")
    entry = await add_log_entry(
        db, LogEntryIn(log_entry_type_id=lt.id, item_id=item.id, values={"cost": 10})
    )
    entry = await update_log_entry(
        db, entry.id, LogEntryPatch(values={"cost": 12}, notes="new brushes")
    )
    assert (entry.values, entry.notes) == ({"cost": 12}, "new brushes")
    assert (await latest_values(db, item_id=item.id))["service"].values == {"cost": 12}
    await delete_log_entry(db, entry.id)
    assert await list_log_entries(db, item_id=item.id) == []
    with pytest.raises(NotFound):
        await delete_log_entry(db, entry.id)


async def test_log_api(client, db):
    unit, lt = await make_cell(db)
    r = await client.post(
        "/api/v1/log-entries",
        json={"log_entry_type_id": lt.id, "unit_id": unit.id, "values": {"capacity_mah": 2950}},
    )
    assert r.status_code == 201
    eid = r.json()["id"]
    assert (await client.get(f"/api/v1/units/{unit.id}/log")).json()[0]["id"] == eid
    latest = (await client.get(f"/api/v1/units/{unit.id}/latest")).json()
    assert latest["capacity_test"]["values"] == {"capacity_mah": 2950}
    r = await client.patch(f"/api/v1/log-entries/{eid}", json={"notes": "ok"})
    assert r.json()["notes"] == "ok"
    assert (await client.get(f"/api/v1/items/{unit.item_id}/log")).json() == []
    assert (await client.delete(f"/api/v1/log-entries/{eid}")).status_code == 204
    assert (await client.get("/api/v1/units/99999/log")).status_code == 404
