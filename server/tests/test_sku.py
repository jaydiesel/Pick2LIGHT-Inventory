from pick2light.core.fields import FieldSpec
from pick2light.core.sku import (
    ensure_unique_code,
    generate_sku,
    generate_unit_code,
    next_sequence,
    pattern_uses_seq,
    render_pattern,
    sanitize_code,
)
from tests.factories import make_category

SCREW_SPECS = [
    FieldSpec(key="thread", label="Thread", type="text"),
    FieldSpec(key="length", label="Length", type="number", number_unit="m", decimals=None),
    FieldSpec(
        key="head",
        label="Head",
        type="select",
        options=[
            {"value": "socket_head", "label": "Socket head", "sku_code": "SHCS"},
            {"value": "pan", "label": "Pan"},
        ],
    ),
]
RES = [FieldSpec(key="resistance", label="R", type="number", number_unit="Ω")]


def render(pattern, values=None, specs=None, prefix="RES", seq=None, **kw):
    return render_pattern(
        pattern, prefix=prefix, values=values or {}, specs=specs or [], seq=seq, **kw
    )


def test_screw_pattern():
    assert (
        render(
            "SCR-{thread}-{length}-{head}",
            prefix="SCR",
            specs=SCREW_SPECS,
            values={"thread": "M3", "length": 10, "head": "socket_head"},
        )
        == "SCR-M3-10-SHCS"
    )


def test_float_whole_number_has_no_trailing_zero():
    out = render("SCR-{length}", specs=SCREW_SPECS, values={"length": 10.0})
    assert out == "SCR-10"


def test_select_without_sku_code_uses_value_uppercased():
    assert render("{head}", specs=SCREW_SPECS, values={"head": "pan"}) == "PAN"


def test_lower_and_upper_modifiers():
    specs = [FieldSpec(key="t", label="T", type="text")]
    assert render("{t|lower}", specs=specs, values={"t": "AbC"}) == "abc"
    assert render("{t|upper}", specs=specs, values={"t": "AbC"}) == "ABC"
    assert render("{t}", specs=specs, values={"t": "abc"}) == "ABC"


def test_si_token_keeps_case():
    p = "{prefix}-{resistance|si}"
    assert render(p, specs=RES, values={"resistance": 4700}) == "RES-4.7k"
    assert render(p, specs=RES, values={"resistance": 0.022}) == "RES-22m"
    assert render(p, specs=RES, values={"resistance": 1e6}) == "RES-1M"


def test_number_without_si_has_no_prefix_and_no_unit():
    assert render("{resistance}", specs=RES, values={"resistance": 4700.0}) == "4700"


def test_seq_padding():
    assert render("{prefix}{seq:4}", prefix="C", seq=42) == "C0042"


def test_sku_token():
    assert render("{sku}-{seq:2}", seq=3, parent_sku="ABC-1") == "ABC-1-03"


def test_missing_value_collapses_separators():
    specs = [FieldSpec(key="x", label="X", type="text"), FieldSpec(key="y", label="Y", type="text")]
    assert render("A-{x}-{y}", specs=specs, values={"y": "y"}) == "A-Y"
    assert render("{x}-{y}", specs=specs, values={"y": "y"}) == "Y"
    assert render("A-{x}.{y}-", specs=specs, values={"y": "y"}) == "A-Y"


def test_sanitize_unicode_and_slashes():
    assert sanitize_code("M3/10 µ Ω") == "M3-10-u"
    assert sanitize_code("  a//b  ") == "a-b"
    assert sanitize_code("μF") == "uF"


def test_pattern_uses_seq():
    assert pattern_uses_seq("{prefix}-{seq:4}")
    assert not pattern_uses_seq("{prefix}-{thread}")


async def test_next_sequence_increments_per_kind(db):
    cat = await make_category(db, "Seq")
    assert await next_sequence(db, cat.id, "sku") == 1
    assert await next_sequence(db, cat.id, "sku") == 2
    assert await next_sequence(db, cat.id, "unit") == 1


async def test_ensure_unique_appends_suffix():
    taken = {"A", "A-2"}

    async def exists(code):
        return code in taken

    assert await ensure_unique_code("A", exists) == "A-3"
    assert await ensure_unique_code("B", exists) == "B"


async def test_generate_sku_uses_ancestor_pattern(db):
    root = await make_category(
        db,
        "Fasteners",
        sku_prefix="FAS",
        sku_pattern="{prefix}-{thread}-{seq:3}",
        fields=[{"key": "thread", "type": "text"}],
    )
    child = await make_category(db, "Screws", parent=root)
    assert await generate_sku(db, child.id, {"thread": "m3"}) == "FAS-M3-001"
    assert await generate_sku(db, child.id, {"thread": "m3"}) == "FAS-M3-002"


async def test_generate_sku_defaults(db):
    cat = await make_category(db, "capacitors")
    assert await generate_sku(db, cat.id, {}) == "CAPA-0001"


async def test_generate_unit_code_default_and_sku_token(db):
    cat = await make_category(db, "Resistors")
    assert await generate_unit_code(db, cat.id, "RESI-0001", {}) == "RESI0001"
    cat2 = await make_category(db, "Boards", unit_id_pattern="{sku}-{seq:2}")
    assert await generate_unit_code(db, cat2.id, "BRD-0001", {}) == "BRD-0001-01"
