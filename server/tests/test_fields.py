import pytest

from pick2light.core.categories import effective_fields
from pick2light.core.fields import (
    FieldSpec,
    display_value,
    display_values,
    text_values,
    validate_values,
)
from pick2light.errors import ValidationFailed
from tests.factories import make_category

OPTS = [
    {"value": "a", "label": "Alpha"},
    {"value": "b", "label": "Bravo"},
]


def spec(key, type_="text", **kw):
    return FieldSpec(key=key, label=key.title(), type=type_, **kw)


def num(key, unit=None, si=True, **kw):
    return spec(key, "number", number_unit=unit, number_si_prefixes=si, **kw)


def fails(specs, raw, **kw):
    with pytest.raises(ValidationFailed) as exc:
        validate_values(specs, raw, **kw)
    return exc.value.fields


def test_number_parses_si():
    assert validate_values([num("resistance", "Ω")], {"resistance": "4k7"}) == {"resistance": 4700}


def test_number_accepts_plain_numbers():
    assert validate_values([num("n")], {"n": 3}) == {"n": 3}
    assert validate_values([num("n")], {"n": 1.5}) == {"n": 1.5}


def test_number_rejects_bool_and_other_types():
    assert "n" in fails([num("n")], {"n": True})
    assert "n" in fails([num("n")], {"n": [1]})
    assert "n" in fails([num("n")], {"n": float("nan")})


def test_number_without_prefixes_rejects_k():
    assert "capacity" in fails([num("capacity", "Ah", si=False)], {"capacity": "2k"})


def test_min_max():
    s = [num("v", "V", min=1, max=10)]
    assert "v" in fails(s, {"v": 0.5})
    assert "v" in fails(s, {"v": "11"})
    assert validate_values(s, {"v": 10}) == {"v": 10}


def test_select_rejects_unknown_option():
    s = [spec("c", "select", options=OPTS)]
    assert "c" in fails(s, {"c": "z"})
    assert validate_values(s, {"c": "a"}) == {"c": "a"}


def test_multi_select_dedupes():
    s = [spec("m", "multi_select", options=OPTS)]
    assert validate_values(s, {"m": ["a", "b", "a"]}) == {"m": ["a", "b"]}
    assert "m" in fails(s, {"m": ["a", "z"]})
    assert "m" in fails(s, {"m": "a"})


def test_boolean_only_bool():
    s = [spec("b", "boolean")]
    assert validate_values(s, {"b": False}) == {"b": False}
    assert "b" in fails(s, {"b": "yes"})
    assert "b" in fails(s, {"b": 1})


def test_date_format():
    s = [spec("d", "date")]
    assert validate_values(s, {"d": "2026-02-28"}) == {"d": "2026-02-28"}
    assert "d" in fails(s, {"d": "2026-13-01"})
    assert "d" in fails(s, {"d": "20260101"})
    assert "d" in fails(s, {"d": "2026-02-30"})


def test_url_scheme():
    s = [spec("u", "url")]
    assert validate_values(s, {"u": "https://example.com/x"}) == {"u": "https://example.com/x"}
    assert "u" in fails(s, {"u": "ftp://example.com"})
    assert "u" in fails(s, {"u": "example.com"})
    assert "u" in fails(s, {"u": "http://"})


def test_file_positive_int():
    s = [spec("f", "file")]
    assert validate_values(s, {"f": 7}) == {"f": 7}
    assert "f" in fails(s, {"f": 0})
    assert "f" in fails(s, {"f": "7"})
    assert "f" in fails(s, {"f": True})


def test_text_is_trimmed():
    assert validate_values([spec("t")], {"t": "  hi "}) == {"t": "hi"}
    assert "t" in fails([spec("t", "long_text")], {"t": 5})


def test_unknown_key_rejected():
    assert fails([spec("t")], {"colour": "red"}) == {"colour": "unknown field"}


def test_required_missing():
    assert fails([spec("t", required=True)], {}) == {"t": "required"}


def test_required_satisfied_by_existing():
    s = [spec("t", required=True)]
    assert validate_values(s, {}, existing={"t": "x"}) == {"t": "x"}


def test_none_removes_key():
    assert validate_values([spec("t")], {"t": None}, existing={"t": "x", "k": 1}) == {"k": 1}
    assert fails([spec("t", required=True)], {"t": None}, existing={"t": "x"}) == {"t": "required"}


def test_empty_text_is_absent_and_triggers_required():
    assert fails([spec("t", required=True)], {"t": "   "}) == {"t": "required"}
    assert validate_values([spec("t")], {"t": ""}, existing={"t": "x"}) == {}


def test_one_message_per_bad_key():
    s = [num("a"), spec("b", "date")]
    assert set(fails(s, {"a": "x", "b": "no", "c": 1})) == {"a", "b", "c"}


def test_update_keeps_stale_values_of_untouched_fields():
    specs = [num("ir", "mΩ")]
    out = validate_values(
        specs, {"ir": 21}, existing={"ir": 25, "old_removed": "x", "label": "not-a-number-now"}
    )
    assert out == {"ir": 21, "old_removed": "x", "label": "not-a-number-now"}


def test_scope_filter():
    specs = [spec("a"), spec("serial", scope="unit")]
    assert fails(specs, {"serial": "1"}, scope="item") == {"serial": "unknown field"}
    assert validate_values(specs, {"serial": "1"}, scope="unit") == {"serial": "1"}
    assert validate_values(specs, {"a": "x", "serial": "1"}) == {"a": "x", "serial": "1"}


def test_required_ignores_out_of_scope_specs():
    specs = [spec("a"), spec("serial", scope="unit", required=True)]
    assert validate_values(specs, {"a": "x"}, scope="item") == {"a": "x"}


def test_text_values_includes_si_tokens():
    tokens = text_values([num("r", "Ω")], {"r": 4700})
    assert "4.7kΩ" in tokens and "4k7" in tokens


def test_text_values_other_types():
    specs = [
        num("cap", "Ah", si=False),
        spec("s", "select", options=OPTS),
        spec("m", "multi_select", options=OPTS),
        spec("b", "boolean"),
        spec("t"),
    ]
    values = {"cap": 2, "s": "a", "m": ["a", "b"], "b": True, "t": "hello", "gone": "x"}
    assert text_values(specs, values) == ["2", "Alpha", "Alpha", "Bravo", "hello"]


def test_from_dict_accepts_log_type_field():
    s = FieldSpec.from_dict(
        {"key": "cycles", "label": "Cycles", "type": "number", "help_text": "x", "order": 1}
    )
    assert s.scope == "item" and s.number_si_prefixes and s.options == []
    assert validate_values([s], {"cycles": "3"}) == {"cycles": 3}


def test_display_value():
    assert display_value(num("r", "Ω", decimals=1), 4700) == "4.7kΩ"
    assert display_value(num("c", "Ah", si=False), 2000) == "2000Ah"
    assert display_value(spec("s", "select", options=OPTS), "b") == "Bravo"
    assert display_value(spec("s", "select", options=OPTS), "gone") == "gone"
    assert display_value(spec("m", "multi_select", options=OPTS), ["a", "b"]) == "Alpha, Bravo"
    assert display_value(spec("b", "boolean"), True) == "Yes"
    assert display_value(spec("b", "boolean"), False) == "No"
    assert display_value(spec("t"), "hi") == "hi"
    assert display_value(num("n"), "junk") == "junk"


def test_display_values_only_defined_keys():
    specs = [num("r", "Ω"), spec("b", "boolean")]
    out = display_values(specs, {"r": 4700, "b": True, "old": 1})
    assert out == {"r": "4.7kΩ", "b": "Yes"}


async def test_effective_fields_scope(db):
    cat = await make_category(
        db,
        "Cells",
        tracking_mode="unit",
        fields=[
            {"key": "chem", "type": "text"},
            {"key": "serial", "type": "text", "scope": "unit"},
        ],
    )
    assert [s.key for s in await effective_fields(db, cat.id)] == ["chem", "serial"]
    assert [s.key for s in await effective_fields(db, cat.id, "unit")] == ["serial"]
