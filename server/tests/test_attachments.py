import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import attachments as svc
from pick2light.core.attachments import (
    add_link,
    attachment_path,
    delete_attachment,
    list_attachments,
    save_upload,
)
from pick2light.core.logs import LogEntryIn, add_log_entry
from pick2light.errors import NotFound, ValidationFailed
from tests.factories import make_category, make_item

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


async def _chunks(data: bytes, size: int = 100) -> AsyncIterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def _upload(
    client: httpx.AsyncClient,
    item_id: int,
    data: bytes = PNG,
    filename: str = "photo.png",
    content_type: str = "image/png",
    kind: str = "photo",
) -> httpx.Response:
    return await client.post(
        "/api/v1/attachments",
        files={"file": (filename, data, content_type)},
        data={"owner_type": "item", "owner_id": str(item_id), "kind": kind},
    )


async def _item_id(db: AsyncSession) -> int:
    return (await make_item(db, await make_category(db))).id


def _stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


async def test_upload_and_download_roundtrip(client: httpx.AsyncClient, db, settings):
    item_id = await _item_id(db)
    r = await _upload(client, item_id)
    assert r.status_code == 201
    body = r.json()
    assert body["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert body["size_bytes"] == len(PNG)
    assert body["filename"] == "photo.png"
    assert body["owner_type"] == "item" and body["owner_id"] == item_id

    f = await client.get(f"/api/v1/attachments/{body['id']}/file")
    assert f.status_code == 200
    assert f.content == PNG
    assert f.headers["content-type"] == "image/png"
    assert f.headers["content-disposition"].startswith("inline")
    assert "photo.png" in f.headers["content-disposition"]
    assert f.headers["x-content-type-options"] == "nosniff"

    listed = await client.get(
        "/api/v1/attachments", params={"owner_type": "item", "owner_id": item_id}
    )
    assert [a["id"] for a in listed.json()] == [body["id"]]
    assert not (settings.data_dir / "attachments" / "tmp").exists() or not list(
        (settings.data_dir / "attachments" / "tmp").iterdir()
    )


async def test_svg_and_html_are_never_inline(client: httpx.AsyncClient, db):
    item_id = await _item_id(db)
    for name, ctype in [("x.svg", "image/svg+xml"), ("x.html", "text/html")]:
        r = await _upload(client, item_id, b"<script>alert(1)</script>", name, ctype, "other")
        f = await client.get(f"/api/v1/attachments/{r.json()['id']}/file")
        assert f.headers["content-disposition"].startswith("attachment")
    pdf = await _upload(client, item_id, b"%PDF-1.4", "d.pdf", "application/pdf", "datasheet")
    f = await client.get(f"/api/v1/attachments/{pdf.json()['id']}/file")
    assert f.headers["content-disposition"].startswith("inline")


async def test_filename_is_sanitised(db, settings):
    item_id = await _item_id(db)
    root = settings.data_dir / "attachments"
    att = await save_upload(
        db,
        owner_type="item",
        owner_id=item_id,
        kind="other",
        filename="../../etc/passwd",
        content_type="text/plain",
        stream=_chunks(b"x"),
        root=root,
    )
    assert att.filename == "passwd"
    att2 = await save_upload(
        db,
        owner_type="item",
        owner_id=item_id,
        kind="other",
        filename="C:\\evil\\..\\a.txt",
        content_type="text/plain",
        stream=_chunks(b"y"),
        root=root,
    )
    assert att2.filename == "a.txt"
    assert attachment_path(att, root=root).is_relative_to(root)


async def test_duplicate_upload_shares_file(db, settings):
    item_id = await _item_id(db)
    root = settings.data_dir / "attachments"
    kw = dict(
        owner_type="item", owner_id=item_id, kind="photo", content_type="image/png", root=root
    )
    a = await save_upload(db, filename="a.png", stream=_chunks(PNG), **kw)
    b = await save_upload(db, filename="b.png", stream=_chunks(PNG), **kw)
    assert a.id != b.id
    assert a.storage_path == b.storage_path
    assert len(_stored_files(root)) == 1
    assert a.storage_path == f"{a.sha256[:2]}/{a.sha256}"


async def test_delete_keeps_shared_file(committed_db, settings):
    root = settings.data_dir / "attachments"
    item_id, a_id = await _committed_attachment(committed_db, root, "a.png")
    async with committed_db() as s:
        b = await save_upload(
            s,
            owner_type="item",
            owner_id=item_id,
            kind="photo",
            filename="b.png",
            content_type="image/png",
            stream=_chunks(PNG),
            root=root,
        )
        b_id = b.id
        await s.commit()
    for gone_id, expect_file in [(a_id, True), (b_id, False)]:
        async with committed_db() as s:
            await delete_attachment(s, gone_id, root=root)
            await s.commit()
        await svc.finish_pending_unlinks()
        assert _blob(root).exists() is expect_file
    async with committed_db() as s:
        assert await list_attachments(s, "item", item_id) == []
        with pytest.raises(NotFound):
            await delete_attachment(s, b_id, root=root)


async def test_deleting_photo_attachment_clears_item_reference(db, settings):
    item = await make_item(db, await make_category(db))
    root = settings.data_dir / "attachments"
    att = await save_upload(
        db,
        owner_type="item",
        owner_id=item.id,
        kind="photo",
        filename="a.png",
        content_type="image/png",
        stream=_chunks(PNG),
        root=root,
    )
    item.photo_attachment_id = att.id
    await db.flush()
    await delete_attachment(db, att.id, root=root)
    await db.refresh(item)
    assert item.photo_attachment_id is None


async def test_upload_too_large(client: httpx.AsyncClient, db, settings, monkeypatch):
    monkeypatch.setattr(svc, "MAX_UPLOAD_BYTES", 10)
    item_id = await _item_id(db)
    r = await _upload(client, item_id, b"x" * 11, "big.bin", "application/octet-stream", "other")
    assert r.status_code == 422
    assert r.json()["fields"] == {"file": "File is larger than 50 MB"}
    root = settings.data_dir / "attachments"
    assert not (root.exists() and _stored_files(root))
    ok = await _upload(client, item_id, b"x" * 10, "ok.bin", "application/octet-stream", "other")
    assert ok.status_code == 201


async def test_stream_error_leaves_no_temp_file(db, settings):
    item_id = await _item_id(db)
    root = settings.data_dir / "attachments"

    async def broken() -> AsyncIterator[bytes]:
        yield b"abc"
        raise ConnectionError("client went away")

    with pytest.raises(ConnectionError):
        await save_upload(
            db,
            owner_type="item",
            owner_id=item_id,
            kind="other",
            filename="a.bin",
            content_type=None,
            stream=broken(),
            root=root,
        )
    assert not (root.exists() and _stored_files(root))


async def test_link_attachment_requires_http_url(client: httpx.AsyncClient, db):
    item_id = await _item_id(db)
    base = {"owner_type": "item", "owner_id": item_id, "kind": "datasheet"}
    for bad in ["javascript:alert(1)", "ftp://x/y.pdf", "not a url", "file:///etc/passwd"]:
        r = await client.post("/api/v1/attachments/link", json={**base, "url": bad})
        assert r.status_code == 422, bad
        assert "url" in r.json()["fields"]
    r = await client.post(
        "/api/v1/attachments/link", json={**base, "url": "https://example.com/ds/lm358.pdf"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["url"] == "https://example.com/ds/lm358.pdf"
    assert body["filename"] == "lm358.pdf"
    assert body["sha256"] is None
    f = await client.get(f"/api/v1/attachments/{body['id']}/file", follow_redirects=False)
    assert f.status_code in (302, 307)
    assert f.headers["location"] == "https://example.com/ds/lm358.pdf"
    d = await client.delete(f"/api/v1/attachments/{body['id']}")
    assert d.status_code == 204


async def test_add_link_service_default_filename(db):
    item_id = await _item_id(db)
    att = await add_link(
        db, owner_type="item", owner_id=item_id, kind="other", url="https://example.com/"
    )
    assert att.filename == "example.com"
    with pytest.raises(ValidationFailed):
        await add_link(db, owner_type="item", owner_id=item_id, kind="other", url="gopher://x")


async def test_owner_must_exist(client: httpx.AsyncClient, db, settings):
    r = await _upload(client, 999999)
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/attachments/link",
        json={"owner_type": "unit", "owner_id": 999999, "kind": "other", "url": "http://x.org/a"},
    )
    assert r.status_code == 404
    root = settings.data_dir / "attachments"
    assert not (root.exists() and _stored_files(root))
    r = await client.get("/api/v1/attachments", params={"owner_type": "bogus", "owner_id": 1})
    assert r.status_code == 422


async def test_owner_types_supported(client: httpx.AsyncClient, db):
    from tests.factories import make_location
    from tests.test_logs import make_cell

    unit, lt = await make_cell(db)
    entry = await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id))
    cat = await make_category(db)
    item = await make_item(db, cat)
    loc = await make_location(db)
    for owner_type, owner_id in [
        ("item", item.id),
        ("unit", unit.id),
        ("location", loc.id),
        ("category", cat.id),
        ("log_entry", entry.id),
    ]:
        r = await client.post(
            "/api/v1/attachments/link",
            json={
                "owner_type": owner_type,
                "owner_id": owner_id,
                "kind": "other",
                "url": "https://example.com/a",
            },
        )
        assert r.status_code == 201, owner_type


async def test_soft_deleted_owner_not_found(db):
    item = await make_item(db, await make_category(db))
    from pick2light.core.items import delete_item

    await delete_item(db, item.id)
    with pytest.raises(NotFound):
        await add_link(db, owner_type="item", owner_id=item.id, kind="other", url="http://x.org/a")


# --- deletion is deferred to commit and coordinated with dedupe -------------------------


async def _committed_attachment(maker, root: Path, filename: str = "a.png") -> tuple[int, int]:
    """Commit an item and one stored attachment; return (item id, attachment id)."""
    async with maker() as s:
        item = await make_item(s, await make_category(s))
        att = await save_upload(
            s,
            owner_type="item",
            owner_id=item.id,
            kind="photo",
            filename=filename,
            content_type="image/png",
            stream=_chunks(PNG),
            root=root,
        )
        await s.commit()
        return item.id, att.id


def _blob(root: Path) -> Path:
    sha = hashlib.sha256(PNG).hexdigest()
    return root / sha[:2] / sha


async def test_delete_rolled_back_keeps_file_and_row(committed_db, settings):
    root = settings.data_dir / "attachments"
    _, att_id = await _committed_attachment(committed_db, root)
    async with committed_db() as s:
        await delete_attachment(s, att_id, root=root)
        assert _blob(root).exists()
        await s.rollback()
    await svc.finish_pending_unlinks()
    assert _blob(root).exists()
    async with committed_db() as s:
        assert (await svc.get_attachment(s, att_id)).id == att_id


async def test_file_removed_only_after_commit(committed_db, settings):
    root = settings.data_dir / "attachments"
    _, att_id = await _committed_attachment(committed_db, root)
    async with committed_db() as s:
        await delete_attachment(s, att_id, root=root)
        await s.flush()
        await svc.finish_pending_unlinks()
        assert _blob(root).exists()
        await s.commit()
    await svc.finish_pending_unlinks()
    assert not _blob(root).exists()


async def test_concurrent_upload_and_delete_of_same_content(committed_db, settings):
    import asyncio

    root = settings.data_dir / "attachments"
    item_id, att_id = await _committed_attachment(committed_db, root)

    deleter = committed_db()
    await delete_attachment(deleter, att_id, root=root)  # uncommitted; holds the content lock

    async def upload_b() -> int:
        async with committed_db() as s:
            att = await save_upload(
                s,
                owner_type="item",
                owner_id=item_id,
                kind="photo",
                filename="b.png",
                content_type="image/png",
                stream=_chunks(PNG),
                root=root,
            )
            await s.commit()
            return att.id

    upload = asyncio.create_task(upload_b())
    await asyncio.sleep(0.3)
    assert not upload.done()  # waiting for the deleter
    await deleter.commit()
    await deleter.close()
    b_id = await asyncio.wait_for(upload, 5)
    await svc.finish_pending_unlinks()

    assert _blob(root).exists()
    async with committed_db() as s:
        b = await svc.get_attachment(s, b_id)
        assert attachment_path(b, root=root).exists()
