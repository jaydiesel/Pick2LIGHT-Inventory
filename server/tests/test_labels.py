import re

import pytest
from factories import RES_FIELDS, make_category, make_item, make_unit
from sqlalchemy import select

from pick2light.labels import render as render_mod
from pick2light.labels.pdf import SHEETS, labels_pdf
from pick2light.labels.render import render_label
from pick2light.labels.templates import item_context, resolve, unit_context
from pick2light.models import LabelTemplate


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf))


def tmpl(layout, w=50, h=30, target="item"):
    return LabelTemplate(name="t", width_mm=w, height_mm=h, dpi=203, target=target, layout=layout)


def test_resolve_tokens_and_missing():
    ctx = {"name": "Resistor", "attrs": {"package": "0805"}}
    assert resolve("{name} / {attrs.package} / {attrs.nope} / {missing.deep}", ctx) == "Resistor / 0805 /  / "


def test_resolve_si_filter_and_upper():
    ctx = {"raw": {"resistance": 4700}, "_units": {"resistance": "Ω"}, "name": "res"}
    assert resolve("{raw.resistance|si} {name|upper}", ctx) == "4.7kΩ RES"


def test_resolve_literal_braces():
    assert resolve("{{literal}} {name}", {"name": "x"}) == "{literal} x"


def test_render_size_matches_template():
    img = render_label(tmpl([]), {})
    assert abs(img.width - 400) <= 1 and abs(img.height - 240) <= 1


def test_qr_gets_resolved_value(monkeypatch):
    seen = []
    real = render_mod.segno.make

    def spy(value, **kw):
        seen.append(value)
        return real(value, **kw)

    monkeypatch.setattr(render_mod.segno, "make", spy)
    img = render_label(
        tmpl([{"type": "barcode", "symbology": "qr", "value": "{sku}", "x": 1, "y": 2, "size": 26}]),
        {"sku": "RES-4.7k-0805"},
    )
    assert seen == ["RES-4.7k-0805"]
    region = img.crop((8, 16, 8 + 200, 16 + 200))
    assert region.getextrema()[0] == 0


def test_datamatrix_encodes_unit_code(monkeypatch):
    seen = []
    real = render_mod.dmtx.encode

    def spy(data, *a, **kw):
        seen.append(data)
        return real(data, *a, **kw)

    monkeypatch.setattr(render_mod.dmtx, "encode", spy)
    img = render_label(
        tmpl(
            [
                {
                    "type": "barcode",
                    "symbology": "datamatrix",
                    "value": "{unit_code}",
                    "x": 1,
                    "y": 1,
                    "size": 12,
                }
            ],
            30,
            15,
            "unit",
        ),
        {"unit_code": "C0042"},
    )
    assert seen == [b"C0042"] and img.getextrema()[0] == 0


def test_code128_renders():
    img = render_label(
        tmpl(
            [
                {
                    "type": "barcode",
                    "symbology": "code128",
                    "value": "ABC-123",
                    "x": 1,
                    "y": 1,
                    "width": 40,
                    "height": 10,
                }
            ]
        ),
        {},
    )
    assert img.getextrema()[0] == 0


def test_text_shrinks_to_fit():
    long = "An extremely long item name that cannot possibly fit on a tiny label at the requested size"
    el = {"type": "text", "value": "{name}", "x": 1, "y": 1, "w": 20, "h": 6, "font_size": 14, "max_lines": 2}
    img = render_label(tmpl([el]), {"name": long})
    bbox = img.point(lambda p: 255 - p).getbbox()
    assert bbox is not None
    px = 203 / 25.4
    assert bbox[2] <= round(21 * px) + 1 and bbox[3] <= round(7 * px) + 1


def test_pdf_single_labels_page_count():
    imgs = [render_label(tmpl([]), {}) for _ in range(6)]
    pdf = labels_pdf(imgs, tmpl([]), None)
    assert pdf.startswith(b"%PDF") and page_count(pdf) == 6


def test_pdf_sheet_start_position():
    sheet = next(s for s in SHEETS if s.id == "a4-3x8")
    imgs = [render_label(tmpl([], 70, 37), {}) for _ in range(20)]
    assert page_count(labels_pdf(imgs, tmpl([], 70, 37), sheet, start_position=4)) == 1
    assert page_count(labels_pdf(imgs, tmpl([], 70, 37), sheet, start_position=5)) == 2


async def test_seeded_templates_exist(db):
    names = {t.name: t.target for t in await db.scalars(select(LabelTemplate))}
    assert {"Item 50×30", "Item 40×30", "Unit 30×15", "Cell wrap 40×30", "Location 50×30"} <= set(names)
    assert names["Unit 30×15"] == "unit" and names["Location 50×30"] == "location"


async def test_unit_context_has_latest_summary(db):
    cat = await make_category(
        db, "Cells", tracking_mode="unit", fields=[{"key": "model", "type": "text", "show_on_label": True}]
    )
    from pick2light.core.categories import FieldDefIn, LogEntryTypeIn, create_log_type
    from pick2light.core.logs import LogEntryIn, add_log_entry

    lt = await create_log_type(
        db,
        cat.id,
        LogEntryTypeIn(
            key="capacity_test",
            name="Capacity Test",
            fields=[FieldDefIn(key="ir_mohm", type="number", number_unit="mΩ")],
            summary_fields=["ir_mohm"],
        ),
    )
    unit = await make_unit(db, await make_item(db, cat, "30Q", attrs={"model": "30Q"}))
    await add_log_entry(db, LogEntryIn(log_entry_type_id=lt.id, unit_id=unit.id, values={"ir_mohm": 22}))
    ctx = await unit_context(db, unit.id)
    assert ctx["unit_code"] == unit.unit_code and ctx["latest"]["capacity_test"]["ir_mohm"] == "22mΩ"
    assert ctx["summary_line"] == "22mΩ" and ctx["label_line"] == "30Q"


async def test_item_context_label_line(db):
    cat = await make_category(db, "Res", fields=[{**f, "show_on_label": True} for f in RES_FIELDS])
    item = await make_item(db, cat, "R", attrs={"resistance": 4700, "package": "0805"})
    ctx = await item_context(db, item.id)
    assert ctx["label_line"] == "4.7kΩ · 0805" and ctx["code"] == item.sku


async def test_label_api(client):
    cat = (await client.post("/api/v1/categories", json={"name": "Misc"})).json()
    item = (await client.post("/api/v1/items", json={"category_id": cat["id"], "name": "Thing"})).json()
    templates = (await client.get("/api/v1/label-templates")).json()
    item_t = next(t for t in templates if t["name"] == "Item 50×30")
    unit_t = next(t for t in templates if t["target"] == "unit")
    r = await client.post(
        "/api/v1/labels/pdf",
        json={"template_id": item_t["id"], "target_type": "item", "ids": [item["id"]], "copies": 2},
    )
    assert (
        r.status_code == 200 and r.headers["content-type"] == "application/pdf" and page_count(r.content) == 2
    )
    r = await client.post(
        "/api/v1/labels/preview", json={"template_id": item_t["id"], "target_type": "item", "id": item["id"]}
    )
    assert r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    r = await client.post(
        "/api/v1/labels/pdf", json={"template_id": unit_t["id"], "target_type": "item", "ids": [item["id"]]}
    )
    assert r.status_code == 422 and "target_type" in r.json()["fields"]
    sheets = (await client.get("/api/v1/label-sheets")).json()
    assert {s["id"] for s in sheets} == {"a4-3x8", "letter-3x10"}
    r = await client.post(
        "/api/v1/label-templates",
        json={
            "name": "Mine",
            "width_mm": 40,
            "height_mm": 20,
            "target": "item",
            "layout": [
                {"type": "text", "value": "{name}", "x": 1, "y": 1, "w": 38, "h": 18, "font_size": 12}
            ],
        },
    )
    assert r.status_code == 201
    r = await client.patch(f"/api/v1/label-templates/{r.json()['id']}", json={"layout": [{"type": "nope"}]})
    assert r.status_code == 422


@pytest.mark.parametrize("symbology", ["qr", "datamatrix", "code128"])
def test_empty_value_skips_barcode(symbology):
    img = render_label(
        tmpl([{"type": "barcode", "symbology": symbology, "value": "{missing}", "x": 1, "y": 1, "size": 10}]),
        {},
    )
    assert img.getextrema() == (255, 255)
