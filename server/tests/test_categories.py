import pytest

from pick2light.core.categories import (
    CategoryIn,
    CategoryPatch,
    FieldDefIn,
    FieldDefPatch,
    LogEntryTypeIn,
    add_field,
    ancestors,
    create_category,
    create_log_type,
    delete_category,
    delete_field,
    delete_log_type,
    descendant_ids,
    effective_field_defs,
    effective_log_types,
    effective_tracking_mode,
    update_category,
    update_field,
)
from pick2light.errors import Conflict, NotFound, ValidationFailed
from tests.factories import make_category

DATASHEET = {"key": "datasheet", "label": "Datasheet", "type": "url"}
RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}


async def test_child_inherits_parent_fields(db):
    root = await make_category(db, "Electronics", fields=[DATASHEET])
    res = await make_category(db, "Resistors", parent=root, fields=[RESISTANCE])
    assert [f.key for f in await effective_field_defs(db, res.id)] == ["datasheet", "resistance"]


async def test_fields_ordered_by_ancestor_then_order(db):
    root = await make_category(db, "Root", fields=[{"key": "b", "type": "text", "order": 2}])
    await add_field(db, root.id, FieldDefIn(key="a", label="a", type="text", order=1))
    child = await make_category(
        db, "Child", parent=root, fields=[{"key": "c", "type": "text", "order": 0}]
    )
    assert [f.key for f in await effective_field_defs(db, child.id)] == ["a", "b", "c"]


async def test_duplicate_key_with_ancestor_refused(db):
    root = await make_category(db, "Electronics", fields=[DATASHEET])
    res = await make_category(db, "Resistors", parent=root)
    with pytest.raises(Conflict):
        await add_field(db, res.id, FieldDefIn.model_validate({"label": "x", **DATASHEET}))


async def test_duplicate_key_with_descendant_refused(db):
    root = await make_category(db, "Electronics")
    await make_category(db, "Resistors", parent=root, fields=[RESISTANCE])
    with pytest.raises(Conflict):
        await add_field(db, root.id, FieldDefIn.model_validate({"label": "x", **RESISTANCE}))


async def test_same_key_in_sibling_branches_allowed(db):
    root = await make_category(db, "Root")
    await make_category(db, "A", parent=root, fields=[RESISTANCE])
    b = await make_category(db, "B", parent=root, fields=[RESISTANCE])
    assert [f.key for f in await effective_field_defs(db, b.id)] == ["resistance"]


async def test_invalid_key_rejected(db):
    with pytest.raises(ValueError):
        FieldDefIn(key="Bad Key", label="x", type="text")


async def test_unit_scope_requires_unit_tracking(db):
    bulk = await make_category(db, "Bulk")
    with pytest.raises(ValidationFailed) as exc:
        await add_field(
            db, bulk.id, FieldDefIn(key="serial", label="Serial", type="text", scope="unit")
        )
    assert "scope" in (exc.value.fields or {})
    unit = await make_category(
        db,
        "Unit",
        tracking_mode="unit",
        fields=[{"key": "serial", "type": "text", "scope": "unit"}],
    )
    child = await make_category(db, "Child", parent=unit)  # inherits unit mode
    await add_field(db, child.id, FieldDefIn(key="cal", label="Cal", type="date", scope="unit"))


async def test_select_requires_options(db):
    cat = await make_category(db)
    for t in ("select", "multi_select"):
        with pytest.raises(ValidationFailed) as exc:
            await add_field(db, cat.id, FieldDefIn(key="pkg", label="Package", type=t))
        assert "options" in (exc.value.fields or {})
    f = await add_field(
        db,
        cat.id,
        FieldDefIn(
            key="pkg", label="Package", type="select", options=[{"value": "smd", "label": "SMD"}]
        ),
    )
    assert f.options == [{"value": "smd", "label": "SMD", "sku_code": None}]


async def test_update_field_revalidates(db):
    cat = await make_category(db, fields=[{"key": "pkg", "type": "text"}])
    f = (await effective_field_defs(db, cat.id))[0]
    with pytest.raises(ValidationFailed):
        await update_field(db, f.id, FieldDefPatch(type="select"))
    f = await update_field(db, f.id, FieldDefPatch(label="Package", required=True))
    assert (f.label, f.required) == ("Package", True)


async def test_update_field_key_conflict(db):
    root = await make_category(db, fields=[DATASHEET])
    child = await make_category(db, "Child", parent=root, fields=[RESISTANCE])
    f = (await effective_field_defs(db, child.id))[1]
    with pytest.raises(Conflict):
        await update_field(db, f.id, FieldDefPatch(key="datasheet"))


async def test_delete_field(db):
    cat = await make_category(db, fields=[DATASHEET])
    f = (await effective_field_defs(db, cat.id))[0]
    await delete_field(db, f.id)
    assert await effective_field_defs(db, cat.id) == []
    with pytest.raises(NotFound):
        await delete_field(db, f.id)


async def test_tracking_mode_inherited(db):
    root = await make_category(db, "Root", tracking_mode="unit")
    child = await make_category(db, "Child", parent=root)
    grand = await make_category(db, "Grand", parent=child, tracking_mode="bulk")
    plain = await make_category(db, "Plain")
    assert await effective_tracking_mode(db, child.id) == "unit"
    assert await effective_tracking_mode(db, grand.id) == "bulk"
    assert await effective_tracking_mode(db, plain.id) == "bulk"


async def test_ancestors_and_descendants(db):
    a = await make_category(db, "A")
    b = await make_category(db, "B", parent=a)
    c = await make_category(db, "C", parent=b)
    other = await make_category(db, "Other", parent=a)
    assert [x.id for x in await ancestors(db, c.id)] == [a.id, b.id, c.id]
    assert sorted(await descendant_ids(db, a.id)) == sorted([a.id, b.id, c.id, other.id])
    assert await descendant_ids(db, c.id) == [c.id]


async def test_delete_category_with_children_refused(db):
    root = await make_category(db, "Root")
    child = await make_category(db, "Child", parent=root)
    with pytest.raises(Conflict):
        await delete_category(db, root.id)
    await delete_category(db, child.id)
    await delete_category(db, root.id)
    with pytest.raises(NotFound):
        await ancestors(db, root.id)


async def test_move_category(db):
    a = await make_category(db, "A")
    b = await make_category(db, "B")
    moved = await update_category(db, b.id, CategoryPatch(parent_id=a.id))
    assert moved.parent_id == a.id
    moved = await update_category(db, b.id, CategoryPatch(parent_id=None))
    assert moved.parent_id is None


async def test_move_category_key_collision_refused(db):
    electronics = await make_category(db, "Electronics", fields=[DATASHEET])
    other = await make_category(db, "Other")
    await make_category(db, "Sub", parent=other, fields=[DATASHEET])
    with pytest.raises(Conflict):
        await update_category(db, other.id, CategoryPatch(parent_id=electronics.id))


async def test_move_into_own_descendant_refused(db):
    a = await make_category(db, "A")
    b = await make_category(db, "B", parent=a)
    with pytest.raises(Conflict):
        await update_category(db, a.id, CategoryPatch(parent_id=b.id))
    with pytest.raises(Conflict):
        await update_category(db, a.id, CategoryPatch(parent_id=a.id))


async def test_move_to_missing_parent(db):
    a = await make_category(db, "A")
    with pytest.raises(NotFound):
        await update_category(db, a.id, CategoryPatch(parent_id=999999))


async def test_patch_only_touches_given_fields(db):
    a = await make_category(db, "A", icon="box", sku_prefix="AA")
    a = await update_category(db, a.id, CategoryPatch(name="A2"))
    assert (a.name, a.icon, a.sku_prefix) == ("A2", "box", "AA")
    a = await update_category(db, a.id, CategoryPatch(icon=None))
    assert a.icon is None


async def test_create_with_missing_parent(db):
    with pytest.raises(NotFound):
        await create_category(db, CategoryIn(name="X", parent_id=999999))


async def test_log_types_inherit_and_conflict(db):
    root = await make_category(db, "Batteries")
    child = await make_category(db, "Li-ion", parent=root)
    lt = await create_log_type(
        db,
        root.id,
        LogEntryTypeIn.model_validate(
            {
                "key": "capacity_test",
                "name": "Capacity Test",
                "applies_to": "unit",
                "fields": [{"key": "mah", "label": "mAh", "type": "number"}],
                "summary_fields": ["mah"],
            }
        ),
    )
    assert [t.id for t in await effective_log_types(db, child.id)] == [lt.id]
    with pytest.raises(Conflict):
        await create_log_type(
            db, child.id, LogEntryTypeIn(key="capacity_test", name="x", applies_to="item")
        )
    with pytest.raises(ValidationFailed) as exc:
        await create_log_type(
            db,
            child.id,
            LogEntryTypeIn(key="other", name="x", applies_to="item", summary_fields=["nope"]),
        )
    assert "summary_fields" in (exc.value.fields or {})
    await delete_log_type(db, lt.id)
    assert await effective_log_types(db, child.id) == []
    # key is free again after a soft delete
    await create_log_type(
        db, child.id, LogEntryTypeIn(key="capacity_test", name="x", applies_to="item")
    )
