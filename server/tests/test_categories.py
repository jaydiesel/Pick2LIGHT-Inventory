import pytest
from factories import make_category

from pick2light.core.categories import (
    CategoryPatch,
    FieldDefIn,
    LogEntryTypeIn,
    add_field,
    create_log_type,
    delete_category,
    effective_field_defs,
    effective_log_types,
    effective_tracking_mode,
    update_category,
)
from pick2light.errors import Conflict, ValidationFailed

DATASHEET = {"key": "datasheet", "label": "Datasheet", "type": "url"}
RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}


async def test_child_inherits_parent_fields(db):
    root = await make_category(db, "Electronics", fields=[DATASHEET])
    res = await make_category(db, "Resistors", parent=root, fields=[RESISTANCE])
    assert [f.key for f in await effective_field_defs(db, res.id)] == ["datasheet", "resistance"]


async def test_duplicate_key_with_ancestor_refused(db):
    root = await make_category(db, "Electronics", fields=[DATASHEET])
    res = await make_category(db, "Resistors", parent=root)
    with pytest.raises(Conflict):
        await add_field(db, res.id, FieldDefIn(**DATASHEET))


async def test_duplicate_key_with_descendant_refused(db):
    root = await make_category(db, "Electronics")
    await make_category(db, "Resistors", parent=root, fields=[RESISTANCE])
    with pytest.raises(Conflict):
        await add_field(db, root.id, FieldDefIn(**RESISTANCE))


async def test_unit_scope_requires_unit_tracking(db):
    cat = await make_category(db, "Screws", tracking_mode="bulk")
    with pytest.raises(ValidationFailed) as e:
        await add_field(db, cat.id, FieldDefIn(key="wrap_color", type="text", scope="unit"))
    assert "scope" in e.value.fields


async def test_tracking_mode_inherited(db):
    root = await make_category(db, "Batteries", tracking_mode="unit")
    cells = await make_category(db, "Cells", parent=root)
    assert await effective_tracking_mode(db, cells.id) == "unit"
    other = await make_category(db, "Misc")
    assert await effective_tracking_mode(db, other.id) == "bulk"


async def test_delete_category_with_children_refused(db):
    root = await make_category(db, "Electronics")
    await make_category(db, "Resistors", parent=root)
    with pytest.raises(Conflict):
        await delete_category(db, root.id)


async def test_move_category_key_collision_refused(db):
    root = await make_category(db, "Electronics", fields=[DATASHEET])
    loose = await make_category(db, "Loose", fields=[DATASHEET])
    with pytest.raises(Conflict):
        await update_category(db, loose.id, CategoryPatch(parent_id=root.id))


async def test_move_into_own_descendant_refused(db):
    root = await make_category(db, "Electronics")
    child = await make_category(db, "Passives", parent=root)
    with pytest.raises(Conflict):
        await update_category(db, root.id, CategoryPatch(parent_id=child.id))


async def test_select_requires_options(db):
    cat = await make_category(db, "Screws")
    with pytest.raises(ValidationFailed) as e:
        await add_field(db, cat.id, FieldDefIn(key="head", type="select", options=[]))
    assert "options" in e.value.fields


async def test_invalid_key_rejected(db):
    cat = await make_category(db, "Screws")
    with pytest.raises(ValidationFailed) as e:
        await add_field(db, cat.id, FieldDefIn(key="Head Type", type="text"))
    assert "key" in e.value.fields


async def test_log_type_inherited_and_summary_checked(db):
    root = await make_category(db, "Batteries", tracking_mode="unit")
    cells = await make_category(db, "Cells", parent=root)
    await create_log_type(
        db,
        root.id,
        LogEntryTypeIn(
            key="capacity_test",
            name="Capacity Test",
            fields=[FieldDefIn(key="capacity_mah", type="number", number_unit="mAh")],
            summary_fields=["capacity_mah"],
        ),
    )
    assert [t.key for t in await effective_log_types(db, cells.id)] == ["capacity_test"]
    with pytest.raises(ValidationFailed) as e:
        await create_log_type(
            db, cells.id, LogEntryTypeIn(key="other", name="Other", fields=[], summary_fields=["nope"])
        )
    assert "summary_fields" in e.value.fields


async def test_effective_fields_returns_specs_filtered_by_scope(db):
    from pick2light.core.categories import effective_fields

    root = await make_category(
        db, "Batteries", tracking_mode="unit", fields=[{"key": "brand", "type": "text"}]
    )
    cells = await make_category(
        db, "Cells", parent=root, fields=[{"key": "wrap_color", "type": "text", "scope": "unit"}]
    )
    assert [s.key for s in await effective_fields(db, cells.id)] == ["brand", "wrap_color"]
    assert [s.key for s in await effective_fields(db, cells.id, scope="unit")] == ["wrap_color"]
