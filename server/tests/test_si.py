import json
import math
from pathlib import Path

import pytest

from pick2light.core.si import format_quantity, parse_quantity, search_tokens

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "shared" / "si-vectors.json").read_text())


@pytest.mark.parametrize(("text", "unit", "expected"), VECTORS["parse"])
def test_parse_vectors(text, unit, expected):
    assert math.isclose(parse_quantity(text, unit), expected, rel_tol=1e-12)


@pytest.mark.parametrize(("text", "unit"), VECTORS["parse_errors"])
def test_parse_errors(text, unit):
    with pytest.raises(ValueError):
        parse_quantity(text, unit)


def test_comma_error_mentions_dot():
    with pytest.raises(ValueError, match="dot"):
        parse_quantity("4,7k", "Ω")


@pytest.mark.parametrize(("value", "unit", "decimals", "expected"), VECTORS["format"])
def test_format_vectors(value, unit, decimals, expected):
    assert format_quantity(value, unit, decimals) == expected


def test_no_prefixes_mode():
    with pytest.raises(ValueError):
        parse_quantity("4.7k", "Ω", allow_prefixes=False)
    assert parse_quantity("4700", "Ω", allow_prefixes=False) == 4700
    assert format_quantity(3000, "mAh", use_prefixes=False) == "3000mAh"


def test_search_tokens():
    assert {"4.7k", "4k7", "4.7kΩ", "4700"} <= set(search_tokens(4700, "Ω"))
