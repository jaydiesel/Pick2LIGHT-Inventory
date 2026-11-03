import re
from typing import Any

import pylibdmtx.pylibdmtx
import pytest
import segno
from PIL import Image
from sqlalchemy import select

from pick2light.labels.pdf import SHEETS, labels_pdf
from pick2light.labels.render import render_label
from pick2light.labels.templates import resolve
from pick2light.models import LabelTemplate
from tests.factories import make_category, make_item, make_location, make_unit

BASE = "/api/v1"


def tmpl(layout: list[dict[str, Any]], w: float = 50, h: float = 30, **kw: Any) -> LabelTemplate:
    return LabelTemplate(
        name="t", width_mm=w, height_mm=h, dpi=203, target=kw.pop("target", "item"), layout=layout
    )


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf))


def dark_pixels(img: Image.Image, box: tuple[int, int, int, int]) -> int:
    return sum(1 for p in img.crop(box).tobytes() if p < 128)


# ----------------------------------------------------------------------------- resolve


def test_resolve_tokens_and_missing():
    ctx = {"name": "Resistor", "attrs": {"pkg": "0805"}, "location": {"path": "A › B"}}
    assert resolve("{name} / {attrs.pkg}", ctx) == "Resistor / 0805"
    assert resolve("[{nope}] [{attrs.nope}] [{name.deeper}]", ctx) == "[] [] []"
    assert resolve("{location.path}", ctx) == "A › B"
    assert resolve("{name|upper}", ctx) == "RESISTOR"
    assert resolve("no tokens", ctx) == "no tokens"


def test_resolve_si_filter():
    ctx = {"attrs": {"r": 4700.0}, "latest": {"cap": {"mah": 2450}}, "_units": {"attrs.r": "Ω"}}
    assert resolve("{attrs.r|si}", ctx) == "4.7kΩ"
    assert resolve("{latest.cap.mah|si}", ctx) == "2.45k"
    assert resolve("{attrs.missing|si}", ctx) == ""
    assert resolve("{name|si}", {"name": "abc"}) == "abc"


def test_resolve_literal_braces():
    assert resolve("{{literal}} {name}", {"name": "x"}) == "{literal} x"
    assert resolve("a {{ b }}", {}) == "a { b }"


# ----------------------------------------------------------------------------- render


def test_render_size_matches_template():
    img = render_label(tmpl([]), {})
    assert img.mode == "L"
    assert abs(img.width - 400) <= 1 and abs(img.height - 240) <= 1


def test_qr_gets_resolved_value(monkeypatch):
    seen: list[Any] = []
    real = segno.make

    def spy(content: Any, *a: Any, **kw: Any) -> Any:
        seen.append(content)
        return real(content, *a, **kw)

    monkeypatch.setattr(segno, "make", spy)
    layout = [{"type": "barcode", "symbology": "qr", "value": "{sku}", "x": 2, "y": 2, "size": 20}]
    img = render_label(tmpl(layout), {"sku": "RES-4.7k-0805"})
    assert seen == ["RES-4.7k-0805"]
    px = round(22 * 203 / 25.4)
    assert dark_pixels(img, (0, 0, px, px)) > 200
    assert dark_pixels(img, (px + 10, 0, 400, 240)) == 0


def test_datamatrix_encodes_unit_code(monkeypatch):
    seen: list[Any] = []
    real = pylibdmtx.pylibdmtx.encode

    def spy(data: Any, *a: Any, **kw: Any) -> Any:
        seen.append(data)
        return real(data, *a, **kw)

    monkeypatch.setattr(pylibdmtx.pylibdmtx, "encode", spy)
    layout = [
        {
            "type": "barcode",
            "symbology": "datamatrix",
            "value": "{unit_code}",
            "x": 1,
            "y": 1,
            "size": 12,
        }
    ]
    img = render_label(tmpl(layout, 30, 15), {"unit_code": "C0042"})
    assert seen == [b"C0042"]
    assert dark_pixels(img, (0, 0, 120, 120)) > 100


def test_one_d_barcodes_draw_bars_and_bad_ean_fails():
    for symbology, value in (("code128", "ABC-123"), ("ean13", "590123412345")):
        layout = [
            {
                "type": "barcode",
                "symbology": symbology,
                "value": value,
                "x": 2,
                "y": 2,
                "width": 40,
                "height": 10,
            }
        ]
        img = render_label(tmpl(layout), {})
        assert dark_pixels(img, (0, 0, 400, 100)) > 300
    bad = [
        {
            "type": "barcode",
            "symbology": "ean13",
            "value": "abc",
            "x": 0,
            "y": 0,
            "width": 30,
            "height": 8,
        }
    ]
    with pytest.raises(ValueError):
        render_label(tmpl(bad), {})


def test_empty_barcode_value_draws_nothing():
    layout = [{"type": "barcode", "symbology": "qr", "value": "{nope}", "x": 0, "y": 0, "size": 20}]
    img = render_label(tmpl(layout), {})
    assert dark_pixels(img, (0, 0, 400, 240)) == 0


def test_text_shrinks_to_fit():
    long_name = "A very long product name that cannot possibly fit on one line " * 3
    layout = [
        {
            "type": "text",
            "value": long_name,
            "x": 5,
            "y": 5,
            "w": 30,
            "h": 6,
            "font_size": 14,
            "bold": True,
        }
    ]
    img = render_label(tmpl(layout), {})
    right = round(35 * 203 / 25.4)
    bottom = round(11 * 203 / 25.4)
    assert dark_pixels(img, (right + 2, 0, 400, 240)) == 0
    assert dark_pixels(img, (0, bottom + 2, 400, 240)) == 0
    assert dark_pixels(img, (0, 0, right, bottom)) > 20


def test_text_wraps_to_max_lines_and_aligns():
    layout = [
        {
            "type": "text",
            "value": "one two three four five six",
            "x": 0,
            "y": 0,
            "w": 20,
            "h": 20,
            "font_size": 10,
            "max_lines": 3,
            "align": "right",
        }
    ]
    img = render_label(tmpl(layout), {})
    box = img.crop((0, 0, round(20 * 203 / 25.4), round(20 * 203 / 25.4))).point(
        lambda p: 255 if p < 128 else 0
    )
    bbox = box.getbbox()
    assert bbox is not None and bbox[2] >= round(20 * 203 / 25.4) - 12


def test_line_box_and_image_elements():
    photo = Image.new("L", (40, 20), 0)
    layout = [
        {"type": "box", "x": 1, "y": 1, "w": 20, "h": 10, "thickness": 0.5},
        {"type": "line", "x": 1, "y": 15, "w": 20, "h": 0, "thickness": 0.5},
        {"type": "image", "source": "item_photo", "x": 25, "y": 1, "w": 20, "h": 20},
    ]
    img = render_label(tmpl(layout), {"_images": {"item_photo": photo}})
    assert dark_pixels(img, (0, 0, 180, 100)) > 100
    assert dark_pixels(img, (190, 0, 400, 180)) > 1000
    # no photo available: element is skipped
    assert dark_pixels(render_label(tmpl(layout[2:]), {}), (0, 0, 400, 240)) == 0


# ----------------------------------------------------------------------------- pdf


def _imgs(n: int) -> list[Image.Image]:
    return [Image.new("L", (400, 240), 0) for _ in range(n)]


def test_pdf_single_labels_page_count():
    pdf = labels_pdf(_imgs(6), tmpl([]), None)
    assert pdf.startswith(b"%PDF")
    assert page_count(pdf) == 6


def test_pdf_sheet_start_position():
    t = tmpl([], 70, 37)
    imgs = [Image.new("L", (560, 296), 0)] * 20
    sheet = SHEETS["a4-3x8"]
    assert sheet.cols * sheet.rows == 24
    assert page_count(labels_pdf(imgs, t, sheet, start_position=4)) == 1
    assert page_count(labels_pdf(imgs, t, sheet, start_position=5)) == 2
    with pytest.raises(ValueError):
        labels_pdf(imgs, t, sheet, start_position=24)


def test_sheet_pdf_page_size_is_sheet_size():
    pdf = labels_pdf(_imgs(1), tmpl([], 70, 37), SHEETS["a4-3x8"])
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    assert m is not None
    assert abs(float(m.group(1)) - 595.3) < 1.5 and abs(float(m.group(2)) - 841.9) < 1.5


# ----------------------------------------------------------------------------- db + api


async def test_seeded_templates_exist(db):
    rows = (await db.scalars(select(LabelTemplate))).all()
    by_name = {r.name: r for r in rows}
    assert {"Item 50×30", "Unit 30×15", "Cell wrap 40×30", "Location 50×30", "Item 40×30"} <= set(
        by_name
    )
    assert by_name["Item 50×30"].target == "item"
    assert by_name["Unit 30×15"].target == "unit"
    assert by_name["Location 50×30"].target == "location"
    assert (by_name["Unit 30×15"].width_mm, by_name["Unit 30×15"].height_mm) == (30, 15)
    assert all(r.dpi == 203 for r in rows)
    for r in rows:  # every seeded layout renders (with empty context) without error
        render_label(r, {})


async def _template_id(client, name: str) -> int:
    rows = (await client.get(f"{BASE}/label-templates")).json()
    return next(r["id"] for r in rows if r["name"] == name)


async def test_template_crud(client):
    body = {
        "name": "Mine",
        "width_mm": 40,
        "height_mm": 20,
        "target": "item",
        "layout": [
            {"type": "text", "value": "{name}", "x": 1, "y": 1, "w": 30, "h": 5, "font_size": 8}
        ],
    }
    r = await client.post(f"{BASE}/label-templates", json=body)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["dpi"] == 203 and r.json()["layout"][0]["type"] == "text"
    r = await client.patch(f"{BASE}/label-templates/{tid}", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed"
    bad = await client.patch(f"{BASE}/label-templates/{tid}", json={"layout": [{"type": "nope"}]})
    assert bad.status_code == 422
    assert (await client.get(f"{BASE}/label-templates/{tid}")).json()["name"] == "Renamed"
    assert (await client.delete(f"{BASE}/label-templates/{tid}")).status_code == 204
    assert (await client.get(f"{BASE}/label-templates/{tid}")).status_code == 404


async def test_delete_template_clears_category_default(client, db):
    tid = await _template_id(client, "Item 40×30")
    cat = await make_category(db, "C", default_label_template_id=tid)
    assert (await client.delete(f"{BASE}/label-templates/{tid}")).status_code == 204
    await db.refresh(cat)
    assert cat.default_label_template_id is None


async def test_label_sheets_listing(client):
    rows = (await client.get(f"{BASE}/label-sheets")).json()
    assert {r["id"] for r in rows} == {"a4-3x8", "letter-3x10"}


async def test_preview_and_pdf_for_item_unit_location(client, db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[{"key": "chem", "type": "text", "show_on_label": True}],
    )
    item = await make_item(db, cat, "18650 cell", attrs={"chem": "Li-ion"})
    unit = await make_unit(db, item)
    loc = await make_location(db, "Drawer")

    for name, target, ident in (
        ("Item 50×30", "item", item.id),
        ("Unit 30×15", "unit", unit.id),
        ("Location 50×30", "location", loc.id),
    ):
        tid = await _template_id(client, name)
        r = await client.post(
            f"{BASE}/labels/preview", json={"template_id": tid, "target_type": target, "id": ident}
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/png"
        assert r.content.startswith(b"\x89PNG")
        r = await client.post(
            f"{BASE}/labels/pdf",
            json={"template_id": tid, "target_type": target, "ids": [ident], "copies": 2},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert page_count(r.content) == 2

    tid = await _template_id(client, "Item 50×30")
    r = await client.post(
        f"{BASE}/labels/pdf",
        json={
            "template_id": tid,
            "target_type": "item",
            "ids": [item.id],
            "copies": 30,
            "sheet_id": "a4-3x8",
            "start_position": 5,
        },
    )
    assert r.status_code == 200 and page_count(r.content) == 2


async def test_pdf_target_mismatch_422(client, db):
    cat = await make_category(db)
    item = await make_item(db, cat)
    tid = await _template_id(client, "Unit 30×15")
    r = await client.post(
        f"{BASE}/labels/pdf", json={"template_id": tid, "target_type": "item", "ids": [item.id]}
    )
    assert r.status_code == 422
    assert r.json()["error"] == "validation"
    r = await client.post(
        f"{BASE}/labels/preview", json={"template_id": tid, "target_type": "item", "id": item.id}
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"copies": 0},
        {"copies": 101},
        {"ids": list(range(1, 502))},
        {"ids": []},
        {"start_position": 24, "sheet_id": "a4-3x8"},
        {"sheet_id": "nope"},
        {"start_position": -1},
    ],
)
async def test_pdf_limits_422(client, db, extra):
    cat = await make_category(db)
    item = await make_item(db, cat)
    tid = await _template_id(client, "Item 50×30")
    body = {"template_id": tid, "target_type": "item", "ids": [item.id], **extra}
    r = await client.post(f"{BASE}/labels/pdf", json=body)
    assert r.status_code == 422, r.text


async def test_pdf_missing_target_404(client):
    tid = await _template_id(client, "Item 50×30")
    r = await client.post(
        f"{BASE}/labels/pdf", json={"template_id": tid, "target_type": "item", "ids": [999999]}
    )
    assert r.status_code == 404
    r = await client.post(
        f"{BASE}/labels/pdf", json={"template_id": 999999, "target_type": "item", "ids": [1]}
    )
    assert r.status_code == 404


async def test_labels_require_auth(auth_client):
    assert (await auth_client.get(f"{BASE}/label-templates")).status_code == 401


async def test_category_default_template_must_exist(client):
    r = await client.post(
        f"{BASE}/categories", json={"name": "X", "default_label_template_id": 999999}
    )
    assert r.status_code == 422
    assert "default_label_template_id" in r.json()["fields"]
