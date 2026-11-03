"""Runtime validation and display of custom field values (stored as JSONB dicts)."""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pick2light.core import si
from pick2light.errors import ValidationFailed

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TEXT_TYPES = ("text", "long_text")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str
    scope: str = "item"
    required: bool = False
    filterable: bool = False
    show_on_label: bool = False
    options: list[dict[str, Any]] = field(default_factory=list)
    number_unit: str | None = None
    number_si_prefixes: bool = True
    min: float | None = None
    max: float | None = None
    decimals: int | None = None

    @classmethod
    def from_definition(cls, fd: Any) -> "FieldSpec":
        return cls(
            key=fd.key,
            label=fd.label,
            type=fd.type,
            scope=fd.scope,
            required=fd.required,
            filterable=fd.filterable,
            show_on_label=fd.show_on_label,
            options=[dict(o) for o in fd.options or []],
            number_unit=fd.number_unit,
            number_si_prefixes=fd.number_si_prefixes,
            min=fd.min,
            max=fd.max,
            decimals=fd.decimals,
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldSpec":
        """Build from a log entry type's field dict (same shape as a definition)."""
        return cls(
            key=d["key"],
            label=d.get("label") or d["key"],
            type=d["type"],
            scope=d.get("scope") or "item",
            required=bool(d.get("required", False)),
            filterable=bool(d.get("filterable", False)),
            show_on_label=bool(d.get("show_on_label", False)),
            options=[dict(o) for o in d.get("options") or []],
            number_unit=d.get("number_unit"),
            number_si_prefixes=bool(d.get("number_si_prefixes", True)),
            min=d.get("min"),
            max=d.get("max"),
            decimals=d.get("decimals"),
        )

    @property
    def option_values(self) -> list[str]:
        return [o["value"] for o in self.options]

    def option_label(self, value: Any) -> str:
        for option in self.options:
            if option["value"] == value:
                return str(option.get("label") or value)
        return str(value)


class _Bad(Exception):
    """A single value failed validation; the message is shown next to the input."""


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _shown(spec: FieldSpec, value: float) -> str:
    try:
        return si.format_quantity(value, spec.number_unit, use_prefixes=spec.number_si_prefixes)
    except ValueError:
        return str(value)


def _number(spec: FieldSpec, value: Any) -> float | int:
    if isinstance(value, str):
        try:
            number: float | int = si.parse_quantity(
                value, spec.number_unit, allow_prefixes=spec.number_si_prefixes
            )
        except ValueError as exc:
            raise _Bad(str(exc)) from None
    elif _is_number(value):
        number = value
    else:
        raise _Bad("Enter a number.")
    if not math.isfinite(number):
        raise _Bad("Enter a finite number.")
    if spec.min is not None and number < spec.min:
        raise _Bad(f"Must be at least {_shown(spec, spec.min)}.")
    if spec.max is not None and number > spec.max:
        raise _Bad(f"Must be at most {_shown(spec, spec.max)}.")
    return number


def _clean(spec: FieldSpec, value: Any) -> Any:
    """Return the value to store, or None when it counts as absent."""
    kind = spec.type
    if kind in _TEXT_TYPES:
        if not isinstance(value, str):
            raise _Bad("Enter text.")
        return value.strip() or None
    if kind == "number":
        return _number(spec, value)
    if kind == "select":
        if not isinstance(value, str) or value not in spec.option_values:
            raise _Bad("Choose one of the options.")
        return value
    if kind == "multi_select":
        if not isinstance(value, list):
            raise _Bad("Choose from the options.")
        allowed = spec.option_values
        if any(not isinstance(v, str) or v not in allowed for v in value):
            raise _Bad("Choose only from the options.")
        return list(dict.fromkeys(value)) or None
    if kind == "boolean":
        if not isinstance(value, bool):
            raise _Bad("Must be true or false.")
        return value
    if kind == "date":
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
            raise _Bad("Use the format YYYY-MM-DD.")
        try:
            date.fromisoformat(value.strip())
        except ValueError:
            raise _Bad("Not a valid date.") from None
        return value.strip()
    if kind == "url":
        text = value.strip() if isinstance(value, str) else ""
        scheme_len = 7 if text.lower().startswith("http://") else 8
        if not text.lower().startswith(("http://", "https://")) or len(text) <= scheme_len:
            raise _Bad("Must start with http:// or https://.")
        return text
    if kind == "file":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise _Bad("Not a valid file.")
        return value
    raise _Bad("Unsupported field type.")


def validate_values(
    specs: Sequence[FieldSpec],
    raw: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Validate `raw` against `specs` and return the merged dict to store.

    `existing` values are the base; `None` in `raw` removes a key. Existing keys without
    a spec are kept untouched. Raises `ValidationFailed` with one message per bad key.
    """
    by_key = {s.key: s for s in specs if scope is None or s.scope == scope}
    merged = dict(existing or {})
    errors: dict[str, str] = {}
    for key, value in raw.items():
        spec = by_key.get(key)
        if spec is None:
            errors[key] = "unknown field"
        elif value is None:
            merged.pop(key, None)
        else:
            try:
                cleaned = _clean(spec, value)
            except _Bad as exc:
                errors[key] = str(exc)
                continue
            if cleaned is None:
                merged.pop(key, None)
            else:
                merged[key] = cleaned
    for key, spec in by_key.items():
        if spec.required and key not in merged and key not in errors:
            errors[key] = "required"
    if errors:
        raise ValidationFailed(errors)
    return merged


def _plain_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def text_values(specs: Sequence[FieldSpec], values: dict[str, Any]) -> list[str]:
    """Strings to index for search, for keys that still have a spec."""
    out: list[str] = []
    for spec in specs:
        value = values.get(spec.key)
        if value is None:
            continue
        if spec.type in (*_TEXT_TYPES, "url", "date") and isinstance(value, str):
            out.append(value)
        elif spec.type == "select":
            out.append(spec.option_label(value))
        elif spec.type == "multi_select" and isinstance(value, list):
            out.extend(spec.option_label(v) for v in value)
        elif spec.type == "number" and _is_number(value):
            if spec.number_si_prefixes:
                try:
                    out.extend(si.search_tokens(value, spec.number_unit))
                    continue
                except ValueError:
                    pass
            out.append(_plain_number(value))
    return out


def display_value(spec: FieldSpec, value: Any) -> str:
    """Human-readable form of a stored value. Never raises on stale or odd data."""
    if spec.type == "number" and _is_number(value):
        try:
            return si.format_quantity(
                value, spec.number_unit, spec.decimals, spec.number_si_prefixes
            )
        except ValueError:
            return str(value)
    if spec.type == "select":
        return spec.option_label(value)
    if spec.type == "multi_select" and isinstance(value, list):
        return ", ".join(spec.option_label(v) for v in value)
    if spec.type == "boolean" and isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def display_values(specs: Sequence[FieldSpec], values: dict[str, Any]) -> dict[str, str]:
    """Display strings for the stored keys that still have a definition (spec order)."""
    return {s.key: display_value(s, values[s.key]) for s in specs if values.get(s.key) is not None}
