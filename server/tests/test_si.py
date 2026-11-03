import json
import math
from pathlib import Path

import pytest

from pick2light.core.si import format_quantity, parse_quantity, search_tokens

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "si-vectors.json").read_text("utf-8")
)


@pytest.mark.parametrize(("text", "unit", "expected"), VECTORS["parse"])
def test_parse_vectors(text: str, unit: str | None, expected: float) -> None:
    assert math.isclose(parse_quantity(text, unit), expected, rel_tol=1e-12, abs_tol=0)


@pytest.mark.parametrize(("text", "unit"), VECTORS["parse_errors"])
def test_parse_errors(text: str, unit: str | None) -> None:
    with pytest.raises(ValueError) as exc:
        parse_quantity(text, unit)
    assert str(exc.value)


def test_comma_error_mentions_dot() -> None:
    with pytest.raises(ValueError, match="dot"):
        parse_quantity("4,7k", "Ω")


def test_parse_is_exact_for_decimal_input() -> None:
    assert parse_quantity("2.2u", "F") == 2.2e-6
    assert parse_quantity("4.7k", "Ω") == 4700.0


@pytest.mark.parametrize(("value", "unit", "decimals", "expected"), VECTORS["format"])
def test_format_vectors(
    value: float, unit: str | None, decimals: int | None, expected: str
) -> None:
    assert format_quantity(value, unit, decimals) == expected


def test_format_uses_micro_sign_u00b5() -> None:
    assert format_quantity(2.2e-6, "F") == "2.2µF"


def test_format_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        format_quantity(float("inf"), "Ω")


def test_format_no_prefixes() -> None:
    assert format_quantity(4700, "Ω", use_prefixes=False) == "4700Ω"
    assert format_quantity(0.1234, "V", decimals=2, use_prefixes=False) == "0.12V"


def test_no_prefixes_mode() -> None:
    with pytest.raises(ValueError):
        parse_quantity("4.7k", "Ω", allow_prefixes=False)
    with pytest.raises(ValueError):
        parse_quantity("4k7", "Ω", allow_prefixes=False)
    assert parse_quantity("4700", "Ω", allow_prefixes=False) == 4700
    assert parse_quantity("3000mAh", "mAh", allow_prefixes=False) == 3000


@pytest.mark.parametrize(
    ("value", "unit"),
    [(4700, "Ω"), (1e-7, "F"), (0.022, "Ω"), (4.7, "Ω"), (-2.2e-6, "F"), (3000, "mAh")],
)
def test_format_then_parse_round_trips(value: float, unit: str) -> None:
    assert parse_quantity(format_quantity(value, unit), unit) == value


def test_search_tokens() -> None:
    assert {"4.7k", "4k7", "4.7kΩ", "4700"} <= set(search_tokens(4700, "Ω"))


def test_search_tokens_micro_and_ohm_r() -> None:
    assert {"2.2u", "2.2µ", "2.2uF", "2.2µF", "2u2"} <= set(search_tokens(2.2e-6, "F"))
    assert {"4R7", "4.7", "4.7Ω"} <= set(search_tokens(4.7, "Ω"))


def test_search_tokens_no_duplicates_and_no_unit() -> None:
    tokens = search_tokens(100, None)
    assert len(tokens) == len(set(tokens))
    assert "100" in tokens
    assert search_tokens(0, "Ω") == ["0", "0Ω", "0ohm"]
