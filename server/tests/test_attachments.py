import hashlib

import pytest
from factories import make_category, make_item

from pick2light.core import attachments as att
from pick2light.errors import NotFound, ValidationFailed


async def stream(data: bytes, size: int = 3):
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def upload(db, root, item, data=b"%PDF-1.4 datasheet", name="ds.pdf"):
    return await att.save_upload(
        db,
        root=root,
        owner_type="item",
        owner_id=item.id,
        kind="datasheet",
        filename=name,
        content_type="application/pdf",
        stream=stream(data),
    )


async def test_upload_and_download_roundtrip(db, tmp_path):
    item = await make_item(db, await make_category(db, "Cells"), "30Q")
    a = await upload(db, tmp_path, item)
    assert a.sha256 == hashlib.sha256(b"%PDF-1.4 datasheet").hexdigest()
    assert a.size_bytes == 18
    assert att.attachment_path(a, tmp_path).read_bytes() == b"%PDF-1.4 datasheet"
    assert [x.id for x in await att.list_attachments(db, "item", item.id)] == [a.id]


async def test_duplicate_upload_shares_file(db, tmp_path):
    item = await make_item(db, await make_category(db, "Cells"), "30Q")
    a = await upload(db, tmp_path, item)
    b = await upload(db, tmp_path, item, name="copy.pdf")
    assert a.storage_path == b.storage_path and a.id != b.id


async def test_delete_keeps_shared_file(db, tmp_path):
    item = await make_item(db, await make_category(db, "Cells"), "30Q")
    a = await upload(db, tmp_path, item)
    b = await upload(db, tmp_path, item, name="copy.pdf")
    await att.delete_attachment(db, a.id, root=tmp_path)
    assert att.attachment_path(b, tmp_path).exists()
    await att.delete_attachment(db, b.id, root=tmp_path)
    assert not att.attachment_path(b, tmp_path).exists()


async def test_upload_too_large(db, tmp_path):
    item = await make_item(db, await make_category(db, "Cells"), "30Q")
    with pytest.raises(ValidationFailed) as e:
        await att.save_upload(
            db,
            root=tmp_path,
            owner_type="item",
            owner_id=item.id,
            kind="photo",
            filename="big.jpg",
            content_type="image/jpeg",
            stream=stream(b"x" * 20),
            max_bytes=10,
        )
    assert "file" in e.value.fields
    assert list((tmp_path / "tmp").glob("*")) == []


async def test_link_attachment_requires_http_url(db):
    item = await make_item(db, await make_category(db, "Cells"), "30Q")
    with pytest.raises(ValidationFailed):
        await att.add_link(
            db, owner_type="item", owner_id=item.id, kind="datasheet", url="file:///etc/passwd"
        )
    a = await att.add_link(
        db, owner_type="item", owner_id=item.id, kind="datasheet", url="https://x.test/30q.pdf"
    )
    assert a.filename == "30q.pdf"


async def test_owner_must_exist(db):
    with pytest.raises(NotFound):
        await att.add_link(
            db, owner_type="item", owner_id=999999, kind="datasheet", url="https://x.test/a.pdf"
        )


async def test_attachment_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Cells"})).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "30Q"})).json()
    r = await client.post(
        "/api/v1/attachments",
        data={"owner_type": "item", "owner_id": str(item["id"]), "kind": "datasheet"},
        files={"file": ("30q.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 201
    a = r.json()
    r = await client.get(f"/api/v1/attachments/{a['id']}/file")
    assert r.status_code == 200 and r.content == b"%PDF-1.4"
    assert r.headers["content-disposition"].startswith("inline")
    listed = (await client.get(f"/api/v1/attachments?owner_type=item&owner_id={item['id']}")).json()
    assert [x["id"] for x in listed] == [a["id"]]
    r = await client.post(
        "/api/v1/attachments/link",
        json={
            "owner_type": "item",
            "owner_id": item["id"],
            "kind": "datasheet",
            "url": "https://x.test/a.pdf",
        },
    )
    assert r.status_code == 201 and r.json()["url"] == "https://x.test/a.pdf"
    assert (await client.delete(f"/api/v1/attachments/{a['id']}")).status_code == 204
