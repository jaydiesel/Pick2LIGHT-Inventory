from sqlalchemy import text

from pick2light.core.categories import LogEntryTypeIn, create_log_type
from pick2light.labels.templates import item_context, location_context, resolve, unit_context
from tests.factories import make_category, make_item, make_location, make_unit


async def test_item_context(db):
    cat = await make_category(
        db,
        "Resistors",
        fields=[
            {"key": "r", "type": "number", "number_unit": "Ω", "show_on_label": True},
            {"key": "pkg", "type": "text", "show_on_label": True},
            {"key": "note", "type": "text"},
        ],
    )
    item = await make_item(
        db, cat, "Resistor", attrs={"r": 4700, "pkg": "0805", "note": "x"}, description="d"
    )
    ctx = await item_context(db, item.id)
    assert ctx["name"] == "Resistor" and ctx["sku"] == item.sku and ctx["category"] == "Resistors"
    assert ctx["attrs"]["r"] == "4.7kΩ"
    assert ctx["attrs_line"] == "4.7kΩ · 0805"
    assert resolve("{attrs.r|si}", ctx) == "4.7kΩ"


async def test_unit_context_latest_and_location(db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "chem", "type": "text", "scope": "unit", "show_on_label": True}],
    )
    lt = await create_log_type(
        db,
        cat.id,
        LogEntryTypeIn.model_validate(
            {
                "key": "capacity_test",
                "name": "Capacity test",
                "applies_to": "unit",
                "fields": [{"key": "mah", "label": "mAh", "type": "number", "number_unit": "Ah"}],
                "summary_fields": ["mah"],
            }
        ),
    )
    item = await make_item(db, cat, "18650")
    room = await make_location(db, "Shed")
    drawer = await make_location(db, "Drawer", parent=room)
    unit = await make_unit(db, item, location_id=drawer.id, attrs={"chem": "NMC"})
    await db.execute(
        text(
            'INSERT INTO log_entry (log_entry_type_id, unit_id, performed_at, "values") VALUES '
            "(:t, :u, now() - interval '1 day', '{\"mah\": 1.0}'),"
            "(:t, :u, now(), '{\"mah\": 2.45}')"
        ),
        {"t": lt.id, "u": unit.id},
    )
    ctx = await unit_context(db, unit.id)
    assert ctx["unit_code"] == unit.unit_code and ctx["name"] == "18650"
    assert ctx["location"]["path"] == "Shed › Drawer" and ctx["location"]["name"] == "Drawer"
    assert ctx["latest"]["capacity_test"]["mah"] == "2.45Ah"
    assert ctx["summary_line"] == "2.45Ah"
    assert ctx["attrs"]["chem"] == "NMC"
    assert ctx["attrs_line"] == "NMC"


async def test_unit_without_location_or_logs(db):
    cat = await make_category(db, "C", tracking_mode="unit")
    unit = await make_unit(db, await make_item(db, cat, "Thing"))
    ctx = await unit_context(db, unit.id)
    assert ctx["location"]["path"] == "" and ctx["summary_line"] == ""


async def test_location_context(db):
    room = await make_location(db, "Shed")
    drawer = await make_location(db, "Drawer", parent=room)
    ctx = await location_context(db, drawer.id)
    assert ctx["name"] == "Drawer" and ctx["code"] == drawer.code
    assert ctx["location"]["path"] == "Shed › Drawer"
