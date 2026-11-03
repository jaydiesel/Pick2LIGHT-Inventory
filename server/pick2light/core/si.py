"""Engineering-unit parsing and formatting (spec §4.1).

Values are stored as plain numbers in the field's base unit; SI prefixes only affect
input parsing and display.
"""

import math
import re
import unicodedata

MICRO = "µ"  # U+00B5, used for display
PREFIX_FACTORS = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "μ": 1e-6,  # U+03BC (NFKC form of U+00B5)
    "m": 1e-3,
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
}
EXP_TO_PREFIX = {-12: "p", -9: "n", -6: MICRO, -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}
OHM = "Ω"  # U+03A9
OHM_ALIASES = ("ohms", "ohm")

_PLAIN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_SUFFIX = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([pnuμmkMGR])?$")
_INFIX = re.compile(r"^([+-]?\d+)([pnuμmkMGR])(\d+)$")


def _norm(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _strip_unit(s: str, unit: str) -> str:
    if unit and s.endswith(unit):
        return s[: -len(unit)].rstrip()
    if unit == OHM:
        lower = s.lower()
        for alias in OHM_ALIASES:
            if lower.endswith(alias):
                return s[: -len(alias)].rstrip()
    return s


def _factor(prefix: str | None, unit: str) -> float:
    if not prefix:
        return 1.0
    if prefix == "R":
        if unit != OHM:
            raise ValueError("R is only valid for resistance values")
        return 1.0
    return PREFIX_FACTORS[prefix]


def parse_quantity(text: str, unit: str | None, allow_prefixes: bool = True) -> float:
    """Parse '4.7k', '4k7', '100nF', '22 mΩ'… into a number in the base unit."""
    unit_n = _norm(unit)
    s = _norm(text).strip()
    if not s:
        raise ValueError("Enter a number")
    if "," in s:
        raise ValueError("Use a dot as the decimal separator (4.7, not 4,7)")
    s = _strip_unit(s, unit_n)
    if _PLAIN.match(s):
        return float(s)
    if not allow_prefixes:
        raise ValueError("Enter a plain number")
    if m := _SUFFIX.match(s):
        return float(m.group(1)) * _factor(m.group(2), unit_n)
    if m := _INFIX.match(s):
        return float(f"{m.group(1)}.{m.group(3)}") * _factor(m.group(2), unit_n)
    raise ValueError(f"Not a valid number: {text!r}")


def _num(value: float, decimals: int | None) -> str:
    places = 6 if decimals is None else decimals
    text = f"{round(value, places):.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _split(value: float, decimals: int | None) -> tuple[str, str]:
    """Return (mantissa text, prefix) for a non-zero value."""
    exp = int(math.floor(math.log10(abs(value)) / 3) * 3)
    exp = max(-12, min(9, exp))
    mantissa = value / 10**exp
    places = 6 if decimals is None else decimals
    if abs(round(mantissa, places)) >= 1000 and exp < 9:
        exp += 3
        mantissa = value / 10**exp
    return _num(mantissa, decimals), EXP_TO_PREFIX[exp]


def format_quantity(
    value: float, unit: str | None, decimals: int | None = None, use_prefixes: bool = True
) -> str:
    unit_s = unit or ""
    if not use_prefixes or value == 0:
        return _num(value, decimals) + unit_s
    mantissa, prefix = _split(value, decimals)
    return f"{mantissa}{prefix}{unit_s}"


def search_tokens(value: float, unit: str | None) -> list[str]:
    """Alternate spellings of a value so text search finds '4.7k', '4k7', '4.7kΩ' and '4700'."""
    tokens: list[str] = []

    def add(t: str) -> None:
        if t and t not in tokens:
            tokens.append(t)

    unit_s = unit or ""
    if value == 0:
        add("0")
        add("0" + unit_s)
        return tokens
    mantissa, prefix = _split(value, None)
    prefixes = [prefix, "u"] if prefix == MICRO else [prefix]
    for p in prefixes:
        add(f"{mantissa}{p}")
        add(f"{mantissa}{p}{unit_s}")
        if p and "." in mantissa:
            whole, frac = mantissa.split(".", 1)
            add(f"{whole}{p}{frac}")
    add(_num(value, None))
    return tokens
