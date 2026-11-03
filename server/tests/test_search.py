from datetime import UTC, datetime

import pytest

from pick2light.core.categories import LogEntryTypeIn, create_log_type
from pick2light.core.items import delete_item
from pick2light.core.logs import LogEntryIn, add_log_entry
from pick2light.core.search import SearchQuery, search
from pick2light.core.stock import add_stock, consume_unit, remove_stock
from pick2light.errors import ValidationFailed
from tests.factories import make_category, make_item, make_location, make_unit

RESISTANCE = {"key": "resistance", "type": "number", "number_unit": "Ω"}
CAPACITANCE = {"key": "capacitance", "type": "number", "number_unit": "F"}


async def ids(db, **kw):
    page = await search(db, SearchQuery.model_validate(kw))
    return [h.id for h in page.hits]


async def test_search_by_name_fuzzy(db):
    cat = await make_category(db, "Parts")
    resistor = await make_item(db, cat, "Resistor 10k")
    await make_item(db, cat, "Capacitor")
    assert await ids(db, q="resistr") == [resistor.id]
    assert await ids(db, q="RESISTOR") == [resistor.id]


async def test_short_query_does_not_flood(db):
    cat = await make_category(db, "Parts")
    for name in ("Alpha", "Apple", "Amp"):
        await make_item(db, cat, name)
    assert await ids(db, q="a") == []


async def test_search_exact_sku_ranks_first(db):
    cat = await make_category(db, "Parts")
    wanted = await make_item(db, cat, "Widget", sku="ABC-1")
    decoy = await make_item(db, cat, "ABC-1 clone", sku="XYZ-9")
    page = await search(db, SearchQuery(q="abc-1"))
    assert [h.id for h in page.hits] == [wanted.id, decoy.id]
    assert page.hits[0].rank == 1000 and page.hits[1].rank < 1000


async def test_search_sku_prefix(db):
    cat = await make_category(db, "Parts")
    item = await make_item(db, cat, "Widget", sku="ZED-0042")
    assert await ids(db, q="zed-00") == [item.id]


async def test_search_unit_code_returns_item_with_unit(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cat, "18650")
    await make_unit(db, item)
    unit = await make_unit(db, item)
    page = await search(db, SearchQuery(q=unit.unit_code))
    assert [(h.id, h.matched_unit_id, h.rank) for h in page.hits] == [(item.id, unit.id, 1000)]
    assert page.location_match is None


async def test_search_location_code_returns_location_match(db):
    cat = await make_category(db, "Parts")
    await make_item(db, cat, "Widget")
    loc = await make_location(db, "Drawer 1")
    page = await search(db, SearchQuery(q=loc.code))
    assert page.hits == [] and page.total == 0
    assert page.location_match is not None
    assert (page.location_match.id, page.location_match.name, page.location_match.code) == (
        loc.id,
        "Drawer 1",
        loc.code,
    )


async def test_search_si_alternates(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    item = await make_item(db, cat, "Part A", attrs={"resistance": "4.7k"})
    await make_item(db, cat, "Part B", attrs={"resistance": "47k"})
    for q in ("4.7k", "4k7", "4.7kΩ", "4700", "4.7kohm", "4.7K"):
        assert await ids(db, q=q) == [item.id], q


async def test_search_ten_kilo_ohm(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    item = await make_item(db, cat, "Part A", attrs={"resistance": "10k"})
    await make_item(db, cat, "Part B", attrs={"resistance": "1k"})
    for q in ("10kΩ", "10k", "10000", "10kohm"):
        assert await ids(db, q=q) == [item.id], q
    assert len(await ids(db, q="Part")) == 2


async def test_search_micro_sign(db):
    cat = await make_category(db, "Parts", fields=[CAPACITANCE])
    item = await make_item(db, cat, "Part C", attrs={"capacitance": "2.2u"})
    await make_item(db, cat, "Part D", attrs={"capacitance": "22u"})
    for q in ("2.2µ", "2.2u", "2.2μ", "2.2µF", "2.2uF", "2u2"):
        assert await ids(db, q=q) == [item.id], q


async def test_filter_number_lt_with_si(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    low = await make_item(db, cat, "Low", attrs={"resistance": "1k"})
    mid = await make_item(db, cat, "Mid", attrs={"resistance": "4.7k"})
    high = await make_item(db, cat, "High", attrs={"resistance": "10k"})
    f = {"key": "resistance", "op": "lt", "value": "5k"}
    got = await ids(db, filters=[f])
    assert sorted(got) == sorted([low.id, mid.id])
    assert await ids(db, filters=[{**f, "op": "gte"}]) == [high.id]
    assert await ids(db, filters=[{**f, "op": "eq", "value": 4700}]) == [mid.id]
    assert sorted(await ids(db, filters=[{**f, "op": "in", "value": ["1k", "10k"]}])) == sorted(
        [low.id, high.id]
    )


async def test_number_filter_survives_stale_non_numeric_value(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    good = await make_item(db, cat, "Good", attrs={"resistance": "1k"})
    stale = await make_item(db, cat, "Stale")
    stale.attrs = {"resistance": "oops"}
    await db.flush()
    assert await ids(db, filters=[{"key": "resistance", "op": "lt", "value": "5k"}]) == [good.id]


async def test_filter_validation_errors(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    await make_item(db, cat, "Good", attrs={"resistance": "1k"})
    with pytest.raises(ValidationFailed):
        await search(db, SearchQuery(filters=[{"key": "nope", "op": "eq", "value": 1}]))
    with pytest.raises(ValidationFailed):
        await search(db, SearchQuery(filters=[{"key": "resistance", "op": "lt", "value": "abc"}]))
    with pytest.raises(ValidationFailed):
        await search(db, SearchQuery(conditions=["broken"]))


async def test_filter_text_contains_escapes_wildcards(db):
    cat = await make_category(db, "Parts", fields=[{"key": "note", "type": "text"}])
    pct = await make_item(db, cat, "Pct", attrs={"note": "50% off"})
    await make_item(db, cat, "Plain", attrs={"note": "500 off"})
    assert await ids(db, filters=[{"key": "note", "op": "contains", "value": "50%"}]) == [pct.id]
    assert await ids(db, filters=[{"key": "note", "op": "contains", "value": "_0"}]) == []


async def test_filter_select_and_multi_select(db):
    opts = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
    cat = await make_category(
        db,
        "Parts",
        fields=[
            {"key": "pkg", "type": "select", "options": opts},
            {"key": "tags", "type": "multi_select", "options": opts},
        ],
    )
    one = await make_item(db, cat, "One", attrs={"pkg": "a", "tags": ["a", "b"]})
    two = await make_item(db, cat, "Two", attrs={"pkg": "b", "tags": ["b"]})
    assert await ids(db, filters=[{"key": "pkg", "op": "eq", "value": "a"}]) == [one.id]
    assert await ids(db, filters=[{"key": "pkg", "op": "ne", "value": "a"}]) == [two.id]
    assert await ids(db, filters=[{"key": "tags", "op": "contains", "value": "a"}]) == [one.id]
    assert sorted(await ids(db, filters=[{"key": "tags", "op": "in", "value": ["a", "b"]}])) == [
        one.id,
        two.id,
    ]


async def test_filter_unit_scope_and_condition(db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "batch", "type": "text", "scope": "unit"}],
    )
    item_a = await make_item(db, cat, "Cell A")
    item_b = await make_item(db, cat, "Cell B")
    await make_unit(db, item_a, attrs={"batch": "B1"}, condition="faulty")
    good = await make_unit(db, item_a, attrs={"batch": "B2"}, condition="new")
    await make_unit(db, item_b, attrs={"batch": "B1"}, condition="new")
    page = await search(db, SearchQuery(filters=[{"key": "batch", "op": "eq", "value": "B2"}]))
    assert [(h.id, h.matched_unit_id) for h in page.hits] == [(item_a.id, good.id)]
    # both constraints must hold on the same unit
    assert await ids(
        db, filters=[{"key": "batch", "op": "eq", "value": "B1"}], conditions=["new"]
    ) == [item_b.id]
    assert await ids(db, conditions=["new", "faulty"]) == [item_a.id, item_b.id]
    assert await ids(db, conditions=["for_parts"]) == []


async def test_unit_filters_ignore_consumed_units(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    item = await make_item(db, cat, "Cell")
    unit = await make_unit(db, item, condition="new")
    assert await ids(db, conditions=["new"]) == [item.id]
    await consume_unit(db, unit.id)
    assert await ids(db, conditions=["new"]) == []


IR_TEST = {
    "key": "capacity_test",
    "name": "Capacity Test",
    "applies_to": "unit",
    "fields": [{"key": "ir_mohm", "label": "IR", "type": "number", "number_unit": "Ω"}],
}


async def test_filter_latest_ir_below_30(db):
    cat = await make_category(db, "Cells", tracking_mode="unit")
    lt = await create_log_type(db, cat.id, LogEntryTypeIn.model_validate(IR_TEST))
    item = await make_item(db, cat, "Cell")
    improved = await make_unit(db, item)  # first bad, latest good
    degraded = await make_unit(db, item)  # first good, latest bad
    untested = await make_unit(db, item)

    def when(day):
        return datetime(2026, 1, day, tzinfo=UTC)

    for unit, day, ir in (
        (improved, 1, 50),
        (improved, 2, 20),
        (degraded, 1, 20),
        (degraded, 2, 50),
    ):
        await add_log_entry(
            db,
            LogEntryIn(
                log_entry_type_id=lt.id,
                unit_id=unit.id,
                performed_at=when(day),
                values={"ir_mohm": ir},
            ),
        )
    assert untested.id
    page = await search(
        db,
        SearchQuery(
            latest=[{"log_type": "capacity_test", "key": "ir_mohm", "op": "lt", "value": 30}]
        ),
    )
    assert [(h.id, h.matched_unit_id) for h in page.hits] == [(item.id, improved.id)]


async def test_filter_latest_item_level(db):
    cat = await make_category(db, "Parts")
    spec = {**IR_TEST, "key": "inspection", "applies_to": "item"}
    lt = await create_log_type(db, cat.id, LogEntryTypeIn.model_validate(spec))
    ok = await make_item(db, cat, "Ok")
    bad = await make_item(db, cat, "Bad")
    for item, ir in ((ok, 10), (bad, 99)):
        await add_log_entry(
            db, LogEntryIn(log_entry_type_id=lt.id, item_id=item.id, values={"ir_mohm": ir})
        )
    f = {"log_type": "inspection", "key": "ir_mohm", "op": "lt", "value": 30}
    assert await ids(db, latest=[f]) == [ok.id]


async def test_filter_location_subtree(db):
    cat = await make_category(db, "Parts")
    unit_cat = await make_category(db, "Cells", tracking_mode="unit")
    room = await make_location(db, "Room")
    drawer = await make_location(db, "Drawer", parent=room)
    other = await make_location(db, "Other")
    bulk_in = await make_item(db, cat, "Bulk in")
    bulk_out = await make_item(db, cat, "Bulk out")
    emptied = await make_item(db, cat, "Emptied")
    cell = await make_item(db, unit_cat, "Cell")
    await add_stock(db, bulk_in.id, drawer.id, 5)
    await add_stock(db, bulk_out.id, other.id, 5)
    await add_stock(db, emptied.id, drawer.id, 0.001)
    await remove_stock(db, emptied.id, drawer.id, 0.001)
    unit = await make_unit(db, cell, location_id=drawer.id)
    page = await search(db, SearchQuery(location_id=room.id))
    assert sorted((h.id, h.matched_unit_id) for h in page.hits) == sorted(
        [(bulk_in.id, None), (cell.id, unit.id)]
    )
    assert await ids(db, location_id=other.id) == [bulk_out.id]


async def test_filter_low_stock(db):
    cat = await make_category(db, "Parts")
    loc = await make_location(db, "Drawer")
    low = await make_item(db, cat, "Low", min_stock=10)
    fine = await make_item(db, cat, "Fine", min_stock=2)
    await make_item(db, cat, "Unset")
    await add_stock(db, low.id, loc.id, 3)
    await add_stock(db, fine.id, loc.id, 3)
    page = await search(db, SearchQuery(low_stock=True))
    assert [(h.id, h.on_hand, h.min_stock) for h in page.hits] == [(low.id, 3, 10)]


async def test_category_subtree(db):
    root = await make_category(db, "Passives")
    child = await make_category(db, "Resistors", parent=root)
    other = await make_category(db, "Tools")
    a = await make_item(db, root, "A")
    b = await make_item(db, child, "B")
    await make_item(db, other, "C")
    assert await ids(db, category_id=root.id) == [a.id, b.id]
    assert await ids(db, category_id=root.id, include_subcategories=False) == [a.id]
    page = await search(db, SearchQuery(category_id=root.id))
    assert [h.category_name for h in page.hits] == ["Passives", "Resistors"]


async def test_deleted_items_hidden(db):
    cat = await make_category(db, "Parts")
    gone = await make_item(db, cat, "Ghost widget")
    kept = await make_item(db, cat, "Ghost keeper")
    await delete_item(db, gone.id)
    assert await ids(db, q="ghost") == [kept.id]
    assert await ids(db, q=gone.sku) == []
    assert await ids(db) == [kept.id]


async def test_pagination_total(db):
    cat = await make_category(db, "Parts")
    made = [await make_item(db, cat, f"Item {n:02d}") for n in range(5)]
    first = await search(db, SearchQuery(limit=2, offset=0))
    second = await search(db, SearchQuery(limit=2, offset=2))
    last = await search(db, SearchQuery(limit=2, offset=4))
    assert (first.total, second.total, last.total) == (5, 5, 5)
    assert [h.id for h in first.hits + second.hits + last.hits] == [m.id for m in made]


async def test_hit_shape_and_attrs_display(db):
    cat = await make_category(db, "Parts", fields=[RESISTANCE])
    loc = await make_location(db, "Drawer")
    item = await make_item(db, cat, "Part A", attrs={"resistance": "4.7k"}, min_stock=1)
    await add_stock(db, item.id, loc.id, 7)
    (hit,) = (await search(db, SearchQuery(q="4k7"))).hits
    assert (hit.id, hit.name, hit.sku, hit.category_id, hit.category_name) == (
        item.id,
        "Part A",
        item.sku,
        cat.id,
        "Parts",
    )
    assert (hit.on_hand, hit.min_stock, hit.matched_unit_id) == (7, 1, None)
    assert hit.attrs_display == {"resistance": "4.7kΩ"}


async def test_search_api(client, db):
    cat = await make_category(db, "Parts")
    item = await make_item(db, cat, "Resistor 10k")
    r = await client.get("/api/v1/search", params={"q": "resistr", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["hits"][0]["id"] == item.id
    r = await client.post("/api/v1/search", json={"q": "resistr", "category_id": cat.id})
    assert [h["id"] for h in r.json()["hits"]] == [item.id]
    r = await client.post("/api/v1/search", json={"limit": 500})
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/search", json={"filters": [{"key": "x", "op": "eq", "value": 1}]}
    )
    assert r.status_code == 422 and r.json()["error"] == "validation"


@pytest.mark.parametrize("q", ["/", "%", "_", "'", '"', "&|!", "Ω", "µ", "a/b", "10k/1%"])
async def test_punctuation_queries_do_not_crash(db, q):
    cat = await make_category(db, "Parts")
    await make_item(db, cat, "Widget 10k/1%")
    page = await search(db, SearchQuery(q=q))
    assert page.total == len(page.hits) <= 1


async def test_field_key_resolved_per_category(db):
    ohm = await make_category(
        db, "Ohm parts", fields=[{"key": "val", "type": "number", "number_unit": "Ω"}]
    )
    volt = await make_category(
        db, "Volt parts", fields=[{"key": "val", "type": "number", "number_unit": "V"}]
    )
    a = await make_item(db, ohm, "A", attrs={"val": "1k"})
    b = await make_item(db, volt, "B", attrs={"val": "1k"})
    f = {"key": "val", "op": "eq", "value": "1kΩ"}
    assert await ids(db, filters=[f], category_id=ohm.id) == [a.id]
    # "1kΩ" is not valid for a volt field: parsed with that category's unit
    with pytest.raises(ValidationFailed):
        await search(db, SearchQuery(filters=[f], category_id=volt.id))
    assert await ids(db, filters=[{**f, "value": "1kV"}], category_id=volt.id) == [b.id]
    with pytest.raises(ValidationFailed) as exc:
        await search(db, SearchQuery(filters=[{**f, "value": "1k"}]))
    assert "val" in str(exc.value.fields)


async def test_inherited_field_resolves_from_child_category(db):
    parent = await make_category(db, "P", fields=[RESISTANCE])
    child = await make_category(db, "C", parent=parent)
    other = await make_category(
        db, "O", fields=[{"key": "resistance", "type": "number", "number_unit": "V"}]
    )
    item = await make_item(db, child, "X", attrs={"resistance": "1k"})
    await make_item(db, other, "Y", attrs={"resistance": "1k"})
    f = {"key": "resistance", "op": "eq", "value": "1k"}
    assert await ids(db, filters=[f], category_id=child.id) == [item.id]


async def test_deleted_category_definitions_ignored(db):
    from pick2light.core.categories import delete_category

    live = await make_category(db, "Live", fields=[RESISTANCE])
    dead = await make_category(
        db, "Dead", fields=[{"key": "resistance", "type": "number", "number_unit": "V"}]
    )
    await delete_category(db, dead.id)
    item = await make_item(db, live, "X", attrs={"resistance": "1k"})
    assert await ids(db, filters=[{"key": "resistance", "op": "eq", "value": "1kΩ"}]) == [item.id]


async def test_latest_log_type_resolved_per_category(db):
    a = await make_category(db, "A", tracking_mode="unit")
    b = await make_category(db, "B", tracking_mode="unit")
    spec_a = IR_TEST
    spec_b = {
        **IR_TEST,
        "fields": [{"key": "ir_mohm", "label": "IR", "type": "number", "number_unit": "V"}],
    }
    await create_log_type(db, a.id, LogEntryTypeIn.model_validate(spec_a))
    await create_log_type(db, b.id, LogEntryTypeIn.model_validate(spec_b))
    f = {"log_type": "capacity_test", "key": "ir_mohm", "op": "lt", "value": "30"}
    await search(db, SearchQuery(latest=[f], category_id=a.id))
    with pytest.raises(ValidationFailed):
        await search(db, SearchQuery(latest=[f]))
