"""Runtime validation of custom field values (spec §3.5)."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pick2light.core import si
from pick2light.errors import ValidationFailed

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    type: str
    label: str | None = None
    scope: str = "item"
    required: bool = False
    filterable: bool = False
    show_on_label: bool = False
    options: list[dict] = field(default_factory=list)
    number_unit: str | None = None
    number_si_prefixes: bool = False
    min: float | None = None
    max: float | None = None
    decimals: int | None = None

    @classmethod
    def from_definition(cls, fd: Any) -> "FieldSpec":
        return cls(
            key=fd.key,
            type=fd.type,
            label=fd.label,
            scope=fd.scope,
            required=fd.required,
            filterable=fd.filterable,
            show_on_label=fd.show_on_label,
            options=list(fd.options or []),
            number_unit=fd.number_unit,
            number_si_prefixes=fd.number_si_prefixes,
            min=fd.min,
            max=fd.max,
            decimals=fd.decimals,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "FieldSpec":
        names = cls.__dataclass_fields__.keys()
        kwargs = {k: v for k, v in d.items() if k in names and v is not None}
        kwargs.setdefault("options", [])
        return cls(**kwargs)

    @property
    def option_values(self) -> list[str]:
        return [o["value"] for o in self.options]

    def option_label(self, value: str) -> str:
        for o in self.options:
            if o["value"] == value:
                return o.get("label") or value
        return value


def _coerce(spec: FieldSpec, value: Any) -> Any:
    """Return the value to store, or raise ValueError with a user-facing message."""
    t = spec.type
    if t in ("text", "long_text"):
        if not isinstance(value, str):
            raise ValueError("Must be text")
        return value.strip()
    if t == "number":
        if isinstance(value, bool):
            raise ValueError("Must be a number")
        if isinstance(value, int | float):
            number = float(value)
        elif isinstance(value, str):
            number = si.parse_quantity(value, spec.number_unit, allow_prefixes=spec.number_si_prefixes)
        else:
            raise ValueError("Must be a number")
        if spec.min is not None and number < spec.min:
            raise ValueError(f"Must be at least {spec.min:g}")
        if spec.max is not None and number > spec.max:
            raise ValueError(f"Must be at most {spec.max:g}")
        return int(number) if number.is_integer() else number
    if t == "select":
        if value not in spec.option_values:
            raise ValueError("Not one of the choices")
        return value
    if t == "multi_select":
        if not isinstance(value, list):
            raise ValueError("Must be a list of choices")
        out: list[str] = []
        for v in value:
            if v not in spec.option_values:
                raise ValueError(f"'{v}' is not one of the choices")
            if v not in out:
                out.append(v)
        return out
    if t == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Must be true or false")
        return value
    if t == "date":
        if not isinstance(value, str) or not _DATE.match(value):
            raise ValueError("Use the format YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Not a valid date") from None
        return value
    if t == "url":
        if not isinstance(value, str) or not value.strip().startswith(("http://", "https://")):
            raise ValueError("Must start with http:// or https://")
        return value.strip()
    if t == "file":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Must be an attachment id")
        return value
    raise ValueError(f"Unsupported field type {t}")


def _absent(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def validate_values(
    specs: list[FieldSpec],
    raw: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Validate submitted keys and merge them over existing values.

    Only submitted keys are validated; stale values of untouched keys are kept as they are.
    """
    active = [s for s in specs if scope is None or s.scope == scope]
    by_key = {s.key: s for s in active}
    result = dict(existing or {})
    errors: dict[str, str] = {}
    for key, value in raw.items():
        spec = by_key.get(key)
        if spec is None:
            errors[key] = "unknown field"
            continue
        if _absent(value):
            result.pop(key, None)
            continue
        try:
            result[key] = _coerce(spec, value)
        except ValueError as exc:
            errors[key] = str(exc)
    for spec in active:
        if spec.required and spec.key not in errors and _absent(result.get(spec.key)):
            errors[spec.key] = "Required"
    if errors:
        raise ValidationFailed(errors)
    return result


def display_value(spec: FieldSpec, value: Any) -> str:
    """Human-readable form of a stored value."""
    if spec.type == "number" and isinstance(value, int | float) and not isinstance(value, bool):
        return si.format_quantity(
            value, spec.number_unit, spec.decimals, use_prefixes=spec.number_si_prefixes
        )
    if spec.type == "select" and isinstance(value, str):
        return spec.option_label(value)
    if spec.type == "multi_select" and isinstance(value, list):
        return ", ".join(spec.option_label(v) for v in value)
    if spec.type == "boolean":
        return "Yes" if value else "No"
    return str(value)


def display_values(specs: list[FieldSpec], values: dict[str, Any]) -> dict[str, str]:
    """Formatted values for keys that still have a definition (removed fields are hidden)."""
    return {s.key: display_value(s, values[s.key]) for s in specs if s.key in values}


def text_values(specs: list[FieldSpec], values: dict[str, Any]) -> list[str]:
    """Strings used to build an item's search text."""
    out: list[str] = []
    for spec in specs:
        if spec.key not in values or spec.type in ("boolean", "file"):
            continue
        value = values[spec.key]
        if spec.type == "number" and isinstance(value, int | float):
            if spec.number_si_prefixes:
                out.extend(si.search_tokens(value, spec.number_unit))
            else:
                out.append(si.format_quantity(value, None, use_prefixes=False))
                if spec.number_unit:
                    out.append(si.format_quantity(value, spec.number_unit, use_prefixes=False))
        elif spec.type == "select" and isinstance(value, str):
            out.extend(dict.fromkeys([value, spec.option_label(value)]))
        elif spec.type == "multi_select" and isinstance(value, list):
            for v in value:
                out.extend(dict.fromkeys([v, spec.option_label(v)]))
        elif isinstance(value, str):
            out.append(value)
    return out
