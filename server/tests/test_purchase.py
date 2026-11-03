import httpx

from tests.factories import make_category, make_item


async def test_purchase_source_crud(client: httpx.AsyncClient, db):
    item = await make_item(db, await make_category(db))
    url = f"/api/v1/items/{item.id}/purchase-sources"
    assert (await client.get(url)).json() == []

    r = await client.post(
        url,
        json={
            "supplier": "Mouser",
            "url": "https://www.mouser.com/p/1",
            "supplier_part_number": "595-LM358",
            "manufacturer_part_number": "LM358P",
            "unit_price": "0.4250",
            "currency": "eur",
            "pack_quantity": 10,
            "last_ordered_at": "2026-10-01",
            "order_reference": "PO-17",
        },
    )
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["item_id"] == item.id
    assert src["currency"] == "EUR"
    assert src["unit_price"] == 0.425
    assert src["last_ordered_at"] == "2026-10-01"

    listed = (await client.get(url)).json()
    assert [s["id"] for s in listed] == [src["id"]]

    p = await client.patch(
        f"/api/v1/purchase-sources/{src['id']}", json={"unit_price": "0.5", "order_reference": None}
    )
    assert p.status_code == 200
    assert p.json()["unit_price"] == 0.5
    assert p.json()["order_reference"] is None
    assert p.json()["supplier"] == "Mouser"

    d = await client.delete(f"/api/v1/purchase-sources/{src['id']}")
    assert d.status_code == 204
    assert (await client.get(url)).json() == []
    assert (await client.delete(f"/api/v1/purchase-sources/{src['id']}")).status_code == 404
    assert (await client.patch(f"/api/v1/purchase-sources/{src['id']}", json={})).status_code == 404


async def test_purchase_source_validation(client: httpx.AsyncClient, db):
    item = await make_item(db, await make_category(db))
    url = f"/api/v1/items/{item.id}/purchase-sources"
    for bad, field in [
        ({"supplier": ""}, "supplier"),
        ({"supplier": "A", "url": "javascript:x"}, "url"),
        ({"supplier": "A", "unit_price": "-1"}, "unit_price"),
        ({"supplier": "A", "currency": "EURO"}, "currency"),
        ({"supplier": "A", "pack_quantity": 0}, "pack_quantity"),
        ({}, "supplier"),
    ]:
        r = await client.post(url, json=bad)
        assert r.status_code == 422, bad
        assert field in r.json()["fields"], bad
    created = await client.post(url, json={"supplier": "A"})
    r = await client.patch(
        f"/api/v1/purchase-sources/{created.json()['id']}", json={"supplier": None}
    )
    assert r.status_code == 422


async def test_purchase_source_item_must_exist(client: httpx.AsyncClient):
    r = await client.post("/api/v1/items/999999/purchase-sources", json={"supplier": "A"})
    assert r.status_code == 404
    assert (await client.get("/api/v1/items/999999/purchase-sources")).status_code == 404
