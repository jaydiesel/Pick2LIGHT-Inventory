from datetime import UTC, datetime

import pytest
from factories import make_category, make_item, make_unit

from pick2light.core.categories import FieldDefIn, LogEntryTypeIn, create_log_type
from pick2light.core.logs import LogEntryIn, add_log_entry, latest_values, list_log_entries
from pick2light.errors import InvalidOperation, ValidationFailed

CAP_FIELDS = [
    FieldDefIn(key="capacity_mah", type="number", number_unit="mAh"),
    FieldDefIn(key="ir_mohm", type="number", number_unit="mΩ"),
    FieldDefIn(key="storage_v", type="number", number_unit="V", decimals=2),
    FieldDefIn(key="tester", type="text"),
]


async def setup(db, on_parent=False):
    parent = await make_category(db, "Batteries", tracking_mode="unit")
    cells = await make_category(db, "Cells", parent=parent)
    lt = await create_log_type(
        db,
        (parent if on_parent else cells).id,
        LogEntryTypeIn(
            key="capacity_test",
            name="Capacity Test",
            fields=CAP_FIELDS,
            summary_fields=["capacity_mah", "ir_mohm", "storage_v"],
        ),
    )
    item = await make_item(db, cells, "30Q")
    unit = await make_unit(db, item)
    return lt, item, unit


def at(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


async def test_add_capacity_test_entry(db):
    lt, _, unit = await setup(db)
    e = await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id,
            unit_id=unit.id,
            values={"capacity_mah": 2950, "ir_mohm": "22", "storage_v": 3.7},
        ),
    )
    assert e.values == {"capacity_mah": 2950, "ir_mohm": 22, "storage_v": 3.7}
    out = await list_log_entries(db, unit_id=unit.id)
    assert out[0].type_key == "capacity_test" and out[0].values_display["ir_mohm"] == "22mΩ"


async def test_values_validated(db):
    lt, _, unit = await setup(db)
    with pytest.raises(ValidationFailed) as e:
        await add_log_entry(
            db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"ir_mohm": "low"})
        )
    assert "ir_mohm" in e.value.fields


async def test_latest_values_pick_newest_by_performed_at(db):
    lt, _, unit = await setup(db)
    await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id, unit_id=unit.id, performed_at=at(2026, 6, 1), values={"ir_mohm": 30}
        ),
    )
    await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id, unit_id=unit.id, performed_at=at(2026, 1, 1), values={"ir_mohm": 20}
        ),
    )
    latest = await latest_values(db, unit_id=unit.id)
    assert latest["capacity_test"].values == {"ir_mohm": 30}
    assert latest["capacity_test"].performed_at == at(2026, 6, 1)


async def test_latest_only_summary_fields(db):
    lt, _, unit = await setup(db)
    await add_log_entry(
        db,
        LogEntryIn(
            log_entry_type_id=lt.id, unit_id=unit.id, values={"ir_mohm": 30, "tester": "Opus BT-C3100"}
        ),
    )
    latest = await latest_values(db, unit_id=unit.id)
    assert latest["capacity_test"].values == {"ir_mohm": 30}
    assert latest["capacity_test"].values_display == {"ir_mohm": "30mΩ"}


async def test_wrong_category_type_refused(db):
    lt, _, _ = await setup(db)
    other = await make_category(db, "Drives", tracking_mode="unit")
    drive = await make_unit(db, await make_item(db, other, "SSD"))
    with pytest.raises(InvalidOperation):
        await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=drive.id, values={}))


async def test_applies_to_mismatch_refused(db):
    lt, item, _ = await setup(db)
    with pytest.raises(InvalidOperation):
        await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, item_id=item.id, values={}))


async def test_exactly_one_target(db):
    lt, item, unit = await setup(db)
    with pytest.raises(ValidationFailed):
        await add_log_entry(
            db, LogEntryIn(log_entry_type_id=lt.id, item_id=item.id, unit_id=unit.id, values={})
        )


async def test_inherited_log_type_allowed(db):
    lt, _, unit = await setup(db, on_parent=True)
    e = await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"ir_mohm": 25}))
    assert e.unit_id == unit.id


async def test_log_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Cells", "tracking_mode": "unit"})).json()
    lt = (
        await client.post(
            f"/api/v1/categories/{cat['id']}/log-types",
            json={
                "key": "capacity_test",
                "name": "Capacity Test",
                "fields": [{"key": "ir_mohm", "type": "number", "number_unit": "mΩ"}],
                "summary_fields": ["ir_mohm"],
            },
        )
    ).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "30Q"})).json()
    unit = (await client.post("/api/v1/units", json={"item_id": item["id"]})).json()
    r = await client.post(
        "/api/v1/log-entries",
        json={"log_entry_type_id": lt["id"], "unit_id": unit["id"], "values": {"ir_mohm": 21}},
    )
    assert r.status_code == 201
    entry = r.json()
    r = await client.patch(
        f"/api/v1/log-entries/{entry['id']}", json={"values": {"ir_mohm": 19}, "notes": "retest"}
    )
    assert r.json()["values"] == {"ir_mohm": 19} and r.json()["notes"] == "retest"
    latest = (await client.get(f"/api/v1/units/{unit['id']}/latest")).json()
    assert latest["capacity_test"]["values"] == {"ir_mohm": 19}
    assert len((await client.get(f"/api/v1/units/{unit['id']}/log")).json()) == 1
    assert (await client.delete(f"/api/v1/log-entries/{entry['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/units/{unit['id']}/latest")).json() == {}
