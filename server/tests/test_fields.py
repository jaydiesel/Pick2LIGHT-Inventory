import pytest

from pick2light.core.fields import FieldSpec, text_values, validate_values
from pick2light.errors import ValidationFailed


def num(key, unit=None, si=False, **kw):
    return FieldSpec(key=key, type="number", number_unit=unit, number_si_prefixes=si, **kw)


def sel(key, *values, multi=False, **kw):
    return FieldSpec(
        key=key,
        type="multi_select" if multi else "select",
        options=[{"value": v, "label": v.upper(), "sku_code": None} for v in values],
        **kw,
    )


def errors_of(specs, raw, **kw):
    with pytest.raises(ValidationFailed) as e:
        validate_values(specs, raw, **kw)
    return e.value.fields


def test_number_parses_si():
    assert validate_values([num("resistance", "Ω", si=True)], {"resistance": "4k7"}) == {"resistance": 4700}


def test_number_accepts_json_numbers():
    assert validate_values([num("length", "mm")], {"length": 10}) == {"length": 10}


def test_number_without_prefixes_rejects_k():
    assert "number" in errors_of([num("capacity", "mAh")], {"capacity": "3k"})["capacity"]


def test_min_max():
    spec = num("ir", "mΩ", min=0, max=500)
    assert "ir" in errors_of([spec], {"ir": 600})
    assert "ir" in errors_of([spec], {"ir": -1})


def test_select_rejects_unknown_option():
    assert "head" in errors_of([sel("head", "hex", "pan")], {"head": "torx"})


def test_multi_select_dedupes():
    out = validate_values([sel("tags", "a", "b", multi=True)], {"tags": ["a", "b", "a"]})
    assert out == {"tags": ["a", "b"]}


def test_date_format():
    spec = FieldSpec(key="tested", type="date")
    assert validate_values([spec], {"tested": "2026-06-01"}) == {"tested": "2026-06-01"}
    assert "tested" in errors_of([spec], {"tested": "2026-13-01"})


def test_url_scheme():
    spec = FieldSpec(key="datasheet", type="url")
    assert "datasheet" in errors_of([spec], {"datasheet": "ftp://x"})
    assert (
        validate_values([spec], {"datasheet": "https://x.test/a.pdf"})["datasheet"] == "https://x.test/a.pdf"
    )


def test_boolean_strict():
    spec = FieldSpec(key="ecc", type="boolean")
    assert validate_values([spec], {"ecc": True}) == {"ecc": True}
    assert "ecc" in errors_of([spec], {"ecc": "yes"})


def test_file_requires_positive_int():
    spec = FieldSpec(key="photo", type="file")
    assert "photo" in errors_of([spec], {"photo": 0})


def test_unknown_key_rejected():
    assert errors_of([num("ir")], {"colour": "red"})["colour"] == "unknown field"


def test_required_missing():
    assert "model" in errors_of([FieldSpec(key="model", type="text", required=True)], {})


def test_none_removes_key():
    out = validate_values([num("ir")], {"ir": None}, existing={"ir": 25})
    assert out == {}


def test_empty_text_is_absent_and_triggers_required():
    spec = FieldSpec(key="model", type="text", required=True)
    assert "model" in errors_of([spec], {"model": "   "})
    assert validate_values([FieldSpec(key="note", type="text")], {"note": "  "}) == {}


def test_update_keeps_stale_values_of_untouched_fields():
    specs = [num("ir", "mΩ")]
    out = validate_values(
        specs, {"ir": 21}, existing={"ir": 25, "old_removed": "x", "label": "not-a-number-now"}
    )
    assert out == {"ir": 21, "old_removed": "x", "label": "not-a-number-now"}


def test_scope_filter():
    specs = [FieldSpec(key="wrap_color", type="text", scope="unit")]
    assert errors_of(specs, {"wrap_color": "blue"}, scope="item")["wrap_color"] == "unknown field"
    assert validate_values(specs, {"wrap_color": "blue"}, scope="unit") == {"wrap_color": "blue"}


def test_required_ignores_other_scope():
    specs = [FieldSpec(key="wrap_color", type="text", scope="unit", required=True)]
    assert validate_values(specs, {}, scope="item") == {}


def test_text_values_includes_si_tokens():
    specs = [num("resistance", "Ω", si=True), sel("package", "0805"), FieldSpec(key="ecc", type="boolean")]
    values = text_values(specs, {"resistance": 4700, "package": "0805", "ecc": True})
    assert "4.7kΩ" in values
    assert "0805" in values
    assert True not in values


def test_from_dict_roundtrip():
    spec = FieldSpec.from_dict(
        {"key": "capacity_mah", "type": "number", "number_unit": "mAh", "label": "Cap"}
    )
    assert spec.key == "capacity_mah" and spec.number_unit == "mAh" and spec.scope == "item"
