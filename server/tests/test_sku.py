from factories import make_category

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

HEADS = [
    {"value": "socket_head", "label": "Socket head", "sku_code": "SHCS"},
    {"value": "pan_head", "label": "Pan head", "sku_code": None},
]
SCREW_SPECS = [
    FieldSpec(key="thread", type="select", options=[{"value": "M3", "label": "M3", "sku_code": None}]),
    FieldSpec(key="length", type="number", number_unit="mm"),
    FieldSpec(key="head", type="select", options=HEADS),
]
RES_SPECS = [FieldSpec(key="resistance", type="number", number_unit="Ω", number_si_prefixes=True)]


def test_screw_pattern():
    out = render_pattern(
        "SCR-{thread}-{length}-{head}",
        prefix="SCR",
        seq=None,
        specs=SCREW_SPECS,
        values={"thread": "M3", "length": 10, "head": "socket_head"},
    )
    assert out == "SCR-M3-10-SHCS"


def test_select_without_sku_code_uses_value_upper():
    out = render_pattern("{head}", prefix="", seq=None, specs=SCREW_SPECS, values={"head": "pan_head"})
    assert out == "PAN_HEAD"


def test_si_token_keeps_case():
    def r(v):
        return render_pattern(
            "{prefix}-{resistance|si}", prefix="RES", seq=None, specs=RES_SPECS, values={"resistance": v}
        )

    assert r(4700) == "RES-4.7k"
    assert r(0.022) == "RES-22m"
    assert r(1e6) == "RES-1M"


def test_lower_filter():
    specs = [FieldSpec(key="color", type="text")]
    assert (
        render_pattern("W-{color|lower}", prefix="", seq=None, specs=specs, values={"color": "Red"})
        == "W-red"
    )


def test_seq_padding():
    assert render_pattern("{prefix}{seq:4}", prefix="C", seq=42, specs=[], values={}) == "C0042"
    assert pattern_uses_seq("{prefix}{seq:4}") and not pattern_uses_seq("{prefix}-{x}")


def test_parent_sku_token():
    assert (
        render_pattern("{sku}-{seq:2}", prefix="", seq=3, specs=[], values={}, parent_sku="CELL-30Q")
        == "CELL-30Q-03"
    )


def test_missing_value_collapses_separators():
    specs = [FieldSpec(key="x", type="text"), FieldSpec(key="y", type="text")]
    assert render_pattern("A-{x}-{y}", prefix="", seq=None, specs=specs, values={"y": "y"}) == "A-Y"
    assert render_pattern("A-{x}-{y}", prefix="", seq=None, specs=specs, values={}) == "A"


def test_sanitize_unicode_and_slashes():
    assert sanitize_code("M3/10 µ Ω") == "M3-10-u"
    assert sanitize_code("  a__b  ") == "a__b"


async def test_next_sequence_increments_per_kind(db):
    cat = await make_category(db, "Cells")
    assert [await next_sequence(db, cat.id, "sku") for _ in range(2)] == [1, 2]
    assert await next_sequence(db, cat.id, "unit") == 1


async def test_ensure_unique_appends_suffix():
    taken = {"A", "A-2"}

    async def exists(code):
        return code in taken

    assert await ensure_unique_code("A", exists) == "A-3"
    assert await ensure_unique_code("B", exists) == "B"


async def test_generate_sku_default_pattern_and_prefix(db):
    cat = await make_category(db, "Resistors")
    assert await generate_sku(db, cat.id, {}) == "RESI-0001"
    assert await generate_sku(db, cat.id, {}) == "RESI-0002"


async def test_generate_sku_uses_ancestor_pattern(db):
    parent = await make_category(db, "Parent", sku_pattern="{prefix}-{seq:3}", sku_prefix="PAR")
    child = await make_category(db, "Child", parent=parent)
    assert await generate_sku(db, child.id, {}) == "PAR-001"


async def test_generate_unit_code(db):
    cat = await make_category(
        db, "Cells", tracking_mode="unit", sku_prefix="CELL", unit_id_pattern="C{seq:4}"
    )
    assert await generate_unit_code(db, cat.id, "CELL-18650-30Q", {}) == "C0001"
    plain = await make_category(db, "Drives", tracking_mode="unit")
    assert await generate_unit_code(db, plain.id, "DRIV-0001", {}) == "DRIV0001"
