from factories import RES_FIELDS, make_category, make_item, make_location, make_unit

from pick2light.core import stock
from pick2light.core.categories import FieldDefIn, LogEntryTypeIn, create_log_type
from pick2light.core.items import delete_item
from pick2light.core.logs import LogEntryIn, add_log_entry
from pick2light.core.search import FieldFilter, LatestFilter, SearchQuery, search

CAP_FIELDS = [{"key": "capacitance", "type": "number", "number_unit": "F", "number_si_prefixes": True}]


async def names(db, **kw):
    page = await search(db, SearchQuery(**kw))
    return [h.name for h in page.hits]


async def resistors(db):
    cat = await make_category(db, "Resistors", fields=[{**f, "filterable": True} for f in RES_FIELDS])
    r47 = await make_item(db, cat, "Resistor 4k7", attrs={"resistance": 4700, "package": "0805"})
    r10 = await make_item(db, cat, "Resistor 10k", attrs={"resistance": 10000, "package": "0603"})
    return cat, r47, r10


async def cells(db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "wrap_color", "type": "text", "scope": "unit", "filterable": True}],
    )
    await create_log_type(
        db,
        cat.id,
        LogEntryTypeIn(
            key="capacity_test",
            name="Capacity Test",
            fields=[FieldDefIn(key="ir_mohm", type="number", number_unit="mΩ")],
            summary_fields=["ir_mohm"],
        ),
    )
    item = await make_item(db, cat, "Samsung 30Q")
    return cat, item


async def test_search_by_name_fuzzy(db):
    await resistors(db)
    assert "Resistor 10k" in await names(db, q="resistr")


async def test_search_exact_sku_ranks_first(db):
    cat, r47, r10 = await resistors(db)
    page = await search(db, SearchQuery(q=r10.sku))
    assert page.hits[0].id == r10.id


async def test_search_unit_code_returns_item_with_unit(db):
    _, item = await cells(db)
    unit = await make_unit(db, item)
    page = await search(db, SearchQuery(q=unit.unit_code))
    assert page.hits[0].id == item.id and page.hits[0].matched_unit_id == unit.id


async def test_search_location_code_returns_location_match(db):
    loc = await make_location(db, "Drawer A1")
    page = await search(db, SearchQuery(q=loc.code))
    assert page.location_match is not None and page.location_match.id == loc.id
    assert page.hits == []


async def test_search_si_alternates(db):
    await resistors(db)
    for q in ("4.7k", "4k7", "4.7kΩ", "4700"):
        assert "Resistor 4k7" in await names(db, q=q), q


async def test_search_micro_sign(db):
    cat = await make_category(db, "Caps", fields=CAP_FIELDS)
    await make_item(db, cat, "Cap", attrs={"capacitance": 2.2e-6})
    assert await names(db, q="2.2µ") == ["Cap"]
    assert await names(db, q="2.2u") == ["Cap"]
    assert await names(db, q="2.2µF") == ["Cap"]


async def test_filter_number_lt_with_si(db):
    await resistors(db)
    out = await names(db, filters=[FieldFilter(key="resistance", op="lt", value="5k")])
    assert out == ["Resistor 4k7"]


async def test_filter_select_eq(db):
    await resistors(db)
    assert await names(db, filters=[FieldFilter(key="package", op="eq", value="0603")]) == ["Resistor 10k"]


async def test_filter_ignores_stale_non_numeric_values(db):
    cat, r47, _ = await resistors(db)
    from sqlalchemy import update

    from pick2light.models import Item

    await db.execute(update(Item).where(Item.id == r47.id).values(attrs={"resistance": "n/a"}))
    assert await names(db, filters=[FieldFilter(key="resistance", op="gt", value=0)]) == ["Resistor 10k"]


async def test_filter_unit_scope_and_condition(db):
    _, item = await cells(db)
    await make_unit(db, item, attrs={"wrap_color": "blue"}, condition="tested_good")
    pink = await make_unit(db, item, attrs={"wrap_color": "pink"}, condition="faulty")
    page = await search(db, SearchQuery(filters=[FieldFilter(key="wrap_color", op="eq", value="pink")]))
    assert [(h.id, h.matched_unit_id) for h in page.hits] == [(item.id, pink.id)]
    assert await names(db, conditions=["for_parts"]) == []
    assert await names(db, conditions=["faulty"]) == ["Samsung 30Q"]


async def test_filter_latest_ir_below_30(db):
    cat, item = await cells(db)
    other = await make_item(db, cat, "LG MJ1")
    good, bad = await make_unit(db, item), await make_unit(db, other)
    lt = (await search(db, SearchQuery())).hits  # warm-up no filters
    assert len(lt) == 2
    from pick2light.core.categories import effective_log_types

    t = (await effective_log_types(db, cat.id))[0]
    await add_log_entry(db, LogEntryIn(log_entry_type_id=t.id, unit_id=good.id, values={"ir_mohm": 22}))
    await add_log_entry(db, LogEntryIn(log_entry_type_id=t.id, unit_id=bad.id, values={"ir_mohm": 45}))
    page = await search(
        db, SearchQuery(latest=[LatestFilter(log_type="capacity_test", key="ir_mohm", op="lt", value=30)])
    )
    assert [(h.name, h.matched_unit_id) for h in page.hits] == [("Samsung 30Q", good.id)]


async def test_filter_location_subtree(db):
    cat, r47, r10 = await resistors(db)
    garage = await make_location(db, "Garage")
    drawer = await make_location(db, "Drawer", parent=garage)
    office = await make_location(db, "Office")
    await stock.add_stock(db, r47.id, drawer.id, 5)
    await stock.add_stock(db, r10.id, office.id, 5)
    assert await names(db, location_id=garage.id) == ["Resistor 4k7"]


async def test_filter_low_stock(db):
    cat, r47, r10 = await resistors(db)
    from pick2light.core.items import ItemPatch, update_item

    await update_item(db, r47.id, ItemPatch(min_stock=10))
    assert await names(db, low_stock=True) == ["Resistor 4k7"]


async def test_category_subtree(db):
    root = await make_category(db, "Electronics")
    res = await make_category(db, "Res", parent=root)
    other = await make_category(db, "Other")
    await make_item(db, res, "R1")
    await make_item(db, other, "X1")
    assert await names(db, category_id=root.id) == ["R1"]
    assert await names(db, category_id=root.id, include_subcategories=False) == []


async def test_deleted_items_hidden(db):
    cat, r47, _ = await resistors(db)
    await delete_item(db, r47.id)
    assert "Resistor 4k7" not in await names(db, q="Resistor")


async def test_pagination_total(db):
    cat = await make_category(db, "Bins")
    for i in range(5):
        await make_item(db, cat, f"Bin {i}")
    page = await search(db, SearchQuery(category_id=cat.id, limit=2, offset=2))
    assert page.total == 5 and [h.name for h in page.hits] == ["Bin 2", "Bin 3"]


async def test_search_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Hot glue sticks"})
    r = await client.get("/api/v1/search", params={"q": "glue"})
    assert r.status_code == 200 and r.json()["hits"][0]["name"] == "Hot glue sticks"
    r = await client.post("/api/v1/search", json={"q": "glue", "limit": 1})
    assert r.json()["total"] == 1 and r.json()["hits"][0]["category_name"] == "Misc"
