from factories import make_category, make_item

from pick2light.core.purchase import (
    PurchaseSourceIn,
    PurchaseSourcePatch,
    create_source,
    list_sources,
    update_source,
)


async def test_purchase_source_crud(db):
    item = await make_item(db, await make_category(db, "Screws"), "M3x10")
    s = await create_source(
        db,
        item.id,
        PurchaseSourceIn(
            supplier="AliExpress",
            url="https://example.test/item/1",
            unit_price=2.5,
            currency="usd",
            pack_quantity=100,
        ),
    )
    assert s.currency == "USD"
    await update_source(db, s.id, PurchaseSourcePatch(unit_price=2.1))
    rows = await list_sources(db, item.id)
    assert [(r.supplier, r.unit_price) for r in rows] == [("AliExpress", 2.1)]


async def test_purchase_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Screws"})).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "M3"})).json()
    r = await client.post(
        f"/api/v1/items/{item['id']}/purchase-sources", json={"supplier": "LCSC", "url": "ftp://x"}
    )
    assert r.status_code == 422 and "url" in r.json()["fields"]
    r = await client.post(
        f"/api/v1/items/{item['id']}/purchase-sources",
        json={"supplier": "LCSC", "supplier_part_number": "C1234"},
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    r = await client.patch(f"/api/v1/purchase-sources/{sid}", json={"order_reference": "PO-7"})
    assert r.json()["order_reference"] == "PO-7"
    assert len((await client.get(f"/api/v1/items/{item['id']}/purchase-sources")).json()) == 1
    assert (await client.delete(f"/api/v1/purchase-sources/{sid}")).status_code == 204
