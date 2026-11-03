"""SKU and unit-code pattern engine (spec §4.2)."""

import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import si
from pick2light.core.categories import ancestors, effective_fields
from pick2light.core.fields import FieldSpec

DEFAULT_SKU_PATTERN = "{prefix}-{seq:4}"
DEFAULT_UNIT_PATTERN = "{prefix}{seq:4}"
_TOKEN = re.compile(r"\{([a-z_][a-z0-9_]*)(?::(\d+))?(?:\|(upper|lower|si))?\}")
_SEPS = re.compile(r"([-_.])[-_.]+")


def sanitize_code(text_in: str) -> str:
    s = unicodedata.normalize("NFKC", text_in).replace("μ", "u").replace("µ", "u")
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9._-]", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def pattern_uses_seq(pattern: str) -> bool:
    return any(m.group(1) == "seq" for m in _TOKEN.finditer(pattern))


def _value_text(spec: FieldSpec | None, value: Any, flt: str | None) -> str:
    if value is None or value == "" or value == []:
        return ""
    if spec is not None and spec.type == "number" and isinstance(value, int | float):
        if flt == "si":
            return si.format_quantity(value, None)
        return si.format_quantity(value, None, use_prefixes=False)
    if spec is not None and spec.type == "select" and isinstance(value, str):
        for o in spec.options:
            if o["value"] == value and o.get("sku_code"):
                value = o["sku_code"]
    if isinstance(value, list):
        value = "-".join(str(v) for v in value)
    if isinstance(value, bool):
        value = "Y" if value else "N"
    s = str(value)
    if flt == "si":
        return s
    return s.lower() if flt == "lower" else s.upper()


def render_pattern(
    pattern: str,
    *,
    prefix: str,
    values: dict,
    specs: list[FieldSpec],
    seq: int | None,
    parent_sku: str | None = None,
) -> str:
    by_key = {s.key: s for s in specs}

    def sub(m: re.Match[str]) -> str:
        name, width, flt = m.group(1), m.group(2), m.group(3)
        if name == "prefix":
            return prefix.upper()
        if name == "seq":
            return "" if seq is None else str(seq).zfill(int(width or 1))
        if name == "sku":
            return parent_sku or ""
        return _value_text(by_key.get(name), values.get(name), flt)

    out = _TOKEN.sub(sub, pattern)
    out = _SEPS.sub(r"\1", out).strip("-_.")
    return sanitize_code(out)


async def next_sequence(db: AsyncSession, category_id: int, kind: Literal["sku", "unit"]) -> int:
    await db.execute(
        text(
            "INSERT INTO category_sequence (category_id, kind, next_value) VALUES (:c, :k, 1) "
            "ON CONFLICT DO NOTHING"
        ),
        {"c": category_id, "k": kind},
    )
    value = await db.scalar(
        text(
            "UPDATE category_sequence SET next_value = next_value + 1 "
            "WHERE category_id = :c AND kind = :k RETURNING next_value - 1"
        ),
        {"c": category_id, "k": kind},
    )
    return int(value)


async def ensure_unique_code(code: str, exists: Callable[[str], Awaitable[bool]]) -> str:
    candidate, n = code, 1
    while await exists(candidate):
        n += 1
        candidate = f"{code}-{n}"
    return candidate


def _default_prefix(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", name))
    return (letters[:4] or "ITEM").upper()


async def _settings_for(db: AsyncSession, category_id: int, attr: str) -> tuple[str | None, str]:
    chain = await ancestors(db, category_id)
    pattern = next((getattr(c, attr) for c in reversed(chain) if getattr(c, attr)), None)
    prefix = next((c.sku_prefix for c in reversed(chain) if c.sku_prefix), None)
    return pattern, prefix or _default_prefix(chain[-1].name)


async def generate_sku(db: AsyncSession, category_id: int, values: dict) -> str:
    pattern, prefix = await _settings_for(db, category_id, "sku_pattern")
    pattern = pattern or DEFAULT_SKU_PATTERN
    specs = await effective_fields(db, category_id)
    seq = await next_sequence(db, category_id, "sku") if pattern_uses_seq(pattern) else None
    out = render_pattern(pattern, prefix=prefix, values=values, specs=specs, seq=seq)
    if not out:
        seq = seq or await next_sequence(db, category_id, "sku")
        out = render_pattern(DEFAULT_SKU_PATTERN, prefix=prefix, values={}, specs=[], seq=seq)
    return out


async def generate_unit_code(db: AsyncSession, category_id: int, item_sku: str, values: dict) -> str:
    pattern, prefix = await _settings_for(db, category_id, "unit_id_pattern")
    pattern = pattern or DEFAULT_UNIT_PATTERN
    specs = await effective_fields(db, category_id)
    seq = await next_sequence(db, category_id, "unit") if pattern_uses_seq(pattern) else None
    out = render_pattern(pattern, prefix=prefix, values=values, specs=specs, seq=seq, parent_sku=item_sku)
    if not out:
        seq = seq or await next_sequence(db, category_id, "unit")
        out = render_pattern(DEFAULT_UNIT_PATTERN, prefix=prefix, values={}, specs=[], seq=seq)
    return out
