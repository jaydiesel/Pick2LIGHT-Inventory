"""SKU and unit-code pattern engine, plus the per-category sequence counters."""

import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import si
from pick2light.core.categories import ancestors, effective_fields
from pick2light.core.fields import FieldSpec
from pick2light.models.definitions import CategorySequence

DEFAULT_SKU_PATTERN = "{prefix}-{seq:4}"
DEFAULT_UNIT_PATTERN = "{prefix}{seq:4}"

_TOKEN_RE = re.compile(r"\{(\w+)(?::(\d+))?(?:\|(\w+))?\}")
_SEQ_RE = re.compile(r"\{seq(?::\d+)?\}")
_SEPARATOR_RUN_RE = re.compile(r"([-_.])[-_.]+")
_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_code(text: str) -> str:
    """Reduce arbitrary text to the allowed SKU characters ``[A-Za-z0-9._-]``."""
    text = text.replace("µ", "u").replace("μ", "u")  # micro sign, Greek mu
    text = unicodedata.normalize("NFKC", text).replace("µ", "u").replace("μ", "u")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _DISALLOWED_RE.sub("-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def pattern_uses_seq(pattern: str) -> bool:
    return _SEQ_RE.search(pattern) is not None


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _render_value(value: Any, spec: FieldSpec | None, modifier: str | None) -> str:
    if value is None or value == "" or value == []:
        return ""
    if isinstance(value, list):
        parts = [_render_value(v, spec, modifier) for v in value]
        return "-".join(p for p in parts if p)
    if spec is not None and spec.type == "number" and isinstance(value, int | float):
        if isinstance(value, bool):
            return _plain(value)
        use_prefixes = modifier == "si"
        try:
            return si.format_quantity(
                float(value), None, decimals=spec.decimals, use_prefixes=use_prefixes
            )
        except ValueError:
            return _plain(value)
    if spec is not None and spec.type in ("select", "multi_select"):
        option = next((o for o in spec.options if o["value"] == value), None)
        rendered = str(option.get("sku_code") or value) if option else str(value)
    else:
        rendered = _plain(value)
    if modifier in ("si", "lower"):
        return rendered.lower() if modifier == "lower" else rendered
    return rendered.upper()


def render_pattern(
    pattern: str,
    *,
    prefix: str,
    values: dict[str, Any],
    specs: Sequence[FieldSpec],
    seq: int | None,
    parent_sku: str | None = None,
) -> str:
    by_key = {s.key: s for s in specs}

    def replace(match: re.Match[str]) -> str:
        key, width, modifier = match.groups()
        if key == "prefix":
            return prefix
        if key == "sku":
            return parent_sku or ""
        if key == "seq":
            return "" if seq is None else str(seq).zfill(int(width or 0))
        return _render_value(values.get(key), by_key.get(key), modifier)

    rendered = _TOKEN_RE.sub(replace, pattern)
    rendered = _SEPARATOR_RUN_RE.sub(r"\1", rendered).strip("-_.")
    return sanitize_code(rendered)


async def next_sequence(db: AsyncSession, category_id: int, kind: Literal["sku", "unit"]) -> int:
    """Atomically take the next counter value (first call returns 1)."""
    await db.execute(
        insert(CategorySequence)
        .values(category_id=category_id, kind=kind, next_value=1)
        .on_conflict_do_nothing()
    )
    result = await db.execute(
        text(
            "UPDATE category_sequence SET next_value = next_value + 1 "
            "WHERE category_id = :cid AND kind = :kind RETURNING next_value - 1"
        ),
        {"cid": category_id, "kind": kind},
    )
    return int(result.scalar_one())


async def _generate(
    db: AsyncSession,
    category_id: int,
    kind: Literal["sku", "unit"],
    values: dict[str, Any],
    parent_sku: str | None,
) -> str:
    chain = list(reversed(await ancestors(db, category_id)))  # self first
    attr = "sku_pattern" if kind == "sku" else "unit_id_pattern"
    default = DEFAULT_SKU_PATTERN if kind == "sku" else DEFAULT_UNIT_PATTERN
    pattern = next((getattr(c, attr) for c in chain if getattr(c, attr)), default)
    prefix = next((c.sku_prefix for c in chain if c.sku_prefix), None)
    if not prefix:
        letters = "".join(ch for ch in chain[0].name if ch.isalpha())
        prefix = letters[:4].upper()
    seq = await next_sequence(db, category_id, kind) if pattern_uses_seq(pattern) else None
    specs = await effective_fields(db, category_id)
    return render_pattern(
        pattern, prefix=prefix, values=values, specs=specs, seq=seq, parent_sku=parent_sku
    )


async def generate_sku(db: AsyncSession, category_id: int, values: dict[str, Any]) -> str:
    return await _generate(db, category_id, "sku", values, None)


async def generate_unit_code(
    db: AsyncSession, category_id: int, item_sku: str, values: dict[str, Any]
) -> str:
    return await _generate(db, category_id, "unit", values, item_sku)


async def ensure_unique_code(code: str, exists: Callable[[str], Awaitable[bool]]) -> str:
    """Return ``code``, or ``code-2``, ``code-3``... until ``exists`` says it is free."""
    candidate, n = code, 1
    while await exists(candidate):
        n += 1
        candidate = f"{code}-{n}"
    return candidate
