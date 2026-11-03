"""Engineering-unit parsing and formatting (``4.7k``, ``4k7``, ``100nF``, ``22 mΩ``).

Values are plain floats in the field's base unit. Prefixes are case-sensitive:
``m`` is milli, ``M`` is mega. Decimal arithmetic is used internally so that
``2.2u`` parses to exactly ``2.2e-6`` and ``0.022`` formats as ``22m``.

The rules here are mirrored by the TypeScript port; both are checked against
``shared/si-vectors.json``.
"""

import math
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, localcontext

_OHM = "Ω"  # Ω after NFKC (U+2126 OHM SIGN folds to this)
_MICRO_GREEK = "μ"  # µ after NFKC (U+00B5 MICRO SIGN folds to this)
_MICRO_DISPLAY = "µ"  # what we show to users

_PREFIX_EXP = {
    "p": -12,
    "n": -9,
    "u": -6,
    _MICRO_GREEK: -6,
    "m": -3,
    "k": 3,
    "M": 6,
    "G": 9,
}
_EXP_SYMBOL = {-12: "p", -9: "n", -6: _MICRO_DISPLAY, -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}
_MIN_EXP, _MAX_EXP = -12, 9

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?"
_NUM_RE = re.compile(_NUM)
_PLAIN_RE = re.compile(rf"({_NUM})\s*([pnu{_MICRO_GREEK}mkMG])?")
_INFIX_RE = re.compile(rf"([+-]?\d+)([pnu{_MICRO_GREEK}mkMGR])(\d+)")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _display_unit(unit: str | None) -> str:
    return _nfkc(unit).replace(_MICRO_GREEK, _MICRO_DISPLAY) if unit else ""


def _strip_unit(text: str, unit: str) -> str:
    """Remove one trailing unit symbol (or ohm alias) from ``text``."""
    if unit == _OHM:
        lowered = text.lower()
        for alias in ("ohms", "ohm"):
            if lowered.endswith(alias):
                return text[: -len(alias)].rstrip()
        if text.endswith(("R", _OHM)):
            return text[:-1].rstrip()
    elif unit and text.endswith(unit):
        return text[: -len(unit)].rstrip()
    return text


def parse_quantity(text: str, unit: str | None, allow_prefixes: bool = True) -> float:
    """Parse a number typed by a user into the base unit. Raises ``ValueError``."""
    cleaned = _nfkc(text).strip()
    if not cleaned:
        raise ValueError("Enter a number.")
    if "," in cleaned:
        raise ValueError("Use a dot for decimals, not a comma.")
    base_unit = _nfkc(unit) if unit else ""
    body = _strip_unit(cleaned, base_unit)

    mantissa: str
    exponent: int
    used_prefix: bool
    plain = _PLAIN_RE.fullmatch(body)
    infix = _INFIX_RE.fullmatch(body)
    if plain:
        mantissa, symbol = plain.group(1), plain.group(2)
        exponent = _PREFIX_EXP[symbol] if symbol else 0
        used_prefix = bool(symbol)
    elif infix and (infix.group(2) != "R" or base_unit == _OHM):
        symbol = infix.group(2)
        mantissa = f"{infix.group(1)}.{infix.group(3)}"
        exponent = _PREFIX_EXP.get(symbol, 0)
        used_prefix = True
    else:
        lead = _NUM_RE.match(body)
        rest = body[lead.end() :].strip() if lead else ""
        if rest:
            raise ValueError(f'"{rest}" is not a known prefix or unit.')
        raise ValueError(f'"{cleaned}" is not a number.')

    if used_prefix and not allow_prefixes:
        raise ValueError("Enter a plain number, without k, m, µ etc.")

    number = Decimal(mantissa)
    result = float(number.scaleb(exponent))
    if math.isinf(result):
        raise ValueError("Number is too large.")
    if result == 0 and number != 0:
        raise ValueError("Number is too small.")
    return result + 0.0  # turns -0.0 into 0.0


def _scale(value: float, decimals: int | None, use_prefixes: bool) -> tuple[Decimal, int]:
    """Return ``(mantissa, exponent)`` with ``value == mantissa * 10**exponent``."""
    if not math.isfinite(value):
        raise ValueError("Not a finite number.")
    if decimals is not None and decimals < 0:
        raise ValueError("decimals must be 0 or more.")
    with localcontext() as ctx:
        ctx.prec = 400
        exact = Decimal(repr(value))
        if exact == 0:
            return Decimal(0), 0
        exponent = 0
        if use_prefixes:
            exponent = max(_MIN_EXP, min(_MAX_EXP, exact.adjusted() // 3 * 3))
        mantissa = exact.scaleb(-exponent)
        if decimals is not None:
            step = Decimal(1).scaleb(-decimals)
            mantissa = mantissa.quantize(step, ROUND_HALF_UP)
            if use_prefixes and abs(mantissa) >= 1000 and exponent < _MAX_EXP:
                exponent += 3  # rounding carried over, e.g. 999.9999 -> 1k
                mantissa = exact.scaleb(-exponent).quantize(step, ROUND_HALF_UP)
        return mantissa, exponent


def _digits(number: Decimal) -> str:
    """Plain decimal text without exponent or trailing zeros."""
    with localcontext() as ctx:
        ctx.prec = 400
        if number == 0:
            return "0"
        return format(number.normalize(), "f")


def format_quantity(
    value: float,
    unit: str | None,
    decimals: int | None = None,
    use_prefixes: bool = True,
) -> str:
    """Format ``value`` (base unit) for display, e.g. ``4.7kΩ``. Raises ``ValueError``."""
    mantissa, exponent = _scale(value, decimals, use_prefixes)
    return f"{_digits(mantissa)}{_EXP_SYMBOL[exponent]}{_display_unit(unit)}"


def search_tokens(value: float, unit: str | None) -> list[str]:
    """Alternate spellings of a value that a user might search for."""
    mantissa, exponent = _scale(value, None, True)
    digits = _digits(mantissa)
    symbol = _EXP_SYMBOL[exponent]
    shown_unit = _display_unit(unit)
    is_ohm = _nfkc(unit) == _OHM if unit else False

    symbols = [symbol, "u"] if symbol == _MICRO_DISPLAY else [symbol]
    if is_ohm and not symbol and mantissa != 0:
        symbols.append("R")

    bases = [f"{digits}{s}" for s in symbols]
    if "." in digits:
        whole, fraction = digits.split(".")
        bases += [f"{whole}{s}{fraction}" for s in symbols if s]
    bases.append(_digits(Decimal(repr(value))))

    tokens = list(bases)
    with_unit = [b for b in bases if "R" not in b]  # "4R7" already says ohm
    if shown_unit:
        tokens += [f"{b}{shown_unit}" for b in with_unit]
    if is_ohm:
        tokens += [f"{b}ohm" for b in with_unit]
    return list(dict.fromkeys(tokens))
