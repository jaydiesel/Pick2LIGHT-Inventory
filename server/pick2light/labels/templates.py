"""Template layout models, `{token}` resolution and the data a label is rendered from.

Layout elements are positioned in millimetres. A *context* is a nested dict of display
strings (``{"name": ..., "attrs": {"pkg": "0805"}, "latest": {"type_key": {"field": ...}}}``)
plus three reserved keys: ``raw`` mirrors the numeric values (used by ``|si``), ``_units``
maps a token path to its base-unit symbol, and ``_images`` holds preloaded photos.
"""

import asyncio
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import column, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import si
from pick2light.core.attachments import attachment_path
from pick2light.core.categories import effective_fields, effective_log_types, get_category
from pick2light.core.fields import FieldSpec, display_values
from pick2light.core.items import get_item
from pick2light.core.locations import get_location, location_path
from pick2light.core.units import get_unit
from pick2light.models import Attachment, Item, Location

PATH_SEPARATOR = " › "
LINE_SEPARATOR = " · "
MAX_PHOTO_PX = 1600


# --------------------------------------------------------------------------- layout models


class _Element(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BarcodeEl(_Element):
    type: Literal["barcode"] = "barcode"
    symbology: Literal["qr", "datamatrix", "code128", "ean13"]
    value: str
    x: float
    y: float
    size: float | None = Field(default=None, gt=0)  # square codes
    width: float | None = Field(default=None, gt=0)  # 1D codes
    height: float | None = Field(default=None, gt=0)


class TextEl(_Element):
    type: Literal["text"] = "text"
    value: str
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    font_size: float = Field(gt=0, le=200)
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    max_lines: int = Field(default=1, ge=1, le=20)


class ImageEl(_Element):
    type: Literal["image"] = "image"
    source: Literal["item_photo", "location_photo"]
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class LineEl(_Element):
    """A line from (x, y) to (x + w, y + h)."""

    type: Literal["line"] = "line"
    x: float
    y: float
    w: float
    h: float
    thickness: float = Field(default=0.3, gt=0)


class BoxEl(_Element):
    type: Literal["box"] = "box"
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    thickness: float = Field(default=0.3, gt=0)


Element = Annotated[BarcodeEl | TextEl | ImageEl | LineEl | BoxEl, Field(discriminator="type")]
LAYOUT_ADAPTER: TypeAdapter[list[Element]] = TypeAdapter(list[Element])


# --------------------------------------------------------------------------- tokens

_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
_MISSING = object()


def _lookup(ctx: Any, path: str) -> Any:
    node = ctx
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _plain(value: Any) -> str:
    if value is None or value is _MISSING:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _apply_si(ctx: dict[str, Any], path: str) -> str:
    value = _lookup(ctx.get("raw", {}), path)
    if value is _MISSING:
        value = _lookup(ctx, path)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _plain(value)
    unit = (ctx.get("_units") or {}).get(path)
    try:
        return si.format_quantity(float(value), unit)
    except ValueError:
        return _plain(value)


def resolve(template: str, ctx: dict[str, Any]) -> str:
    """Fill ``{path.to.value|filter}`` tokens; missing values are empty, ``{{``/``}}`` literal.

    Filters: ``si`` formats a number with SI prefix and its unit; ``upper`` upper-cases.
    """

    def replace(match: re.Match[str]) -> str:
        whole = match.group(0)
        if whole == "{{":
            return "{"
        if whole == "}}":
            return "}"
        path, *filters = (part.strip() for part in match.group(1).split("|"))
        text = _plain(_lookup(ctx, path))
        for name in filters:
            if name == "si":
                text = _apply_si(ctx, path)
            elif name == "upper":
                text = text.upper()
        return text

    return _TOKEN_RE.sub(replace, template)


# --------------------------------------------------------------------------- context builders

_UNIT_LATEST = table(
    "unit_latest_values", column("unit_id"), column("type_key"), column("log_entry_type_id")
)
_ITEM_LATEST = table(
    "item_latest_values", column("item_id"), column("type_key"), column("log_entry_type_id")
)
_VALUES = column("values", JSONB)  # "values" is a reserved word


def _new_context() -> dict[str, Any]:
    return {
        "name": "",
        "sku": "",
        "unit_code": "",
        "serial_number": "",
        "code": "",
        "description": "",
        "category": "",
        "attrs": {},
        "attrs_line": "",
        "summary_line": "",
        "latest": {},
        "location": {"name": "", "path": "", "code": ""},
        "raw": {"attrs": {}, "latest": {}},
        "_units": {},
        "_images": {},
    }


def _add_values(
    ctx: dict[str, Any], path: tuple[str, ...], specs: list[FieldSpec], values: dict[str, Any]
) -> dict[str, str]:
    """Add display strings, raw numbers and unit symbols of `values` under `path`."""
    shown_node, raw_node = ctx, ctx["raw"]
    for part in path:
        shown_node = shown_node.setdefault(part, {})
        raw_node = raw_node.setdefault(part, {})
    shown = display_values(specs, values)
    shown_node.update(shown)
    for spec in specs:
        if spec.key in shown and spec.type == "number":
            raw_node[spec.key] = values[spec.key]
            if spec.number_unit:
                ctx["_units"][".".join((*path, spec.key))] = spec.number_unit
    return shown


async def _fill_attrs(
    db: AsyncSession, ctx: dict[str, Any], item: Item, unit_attrs: dict[str, Any] | None
) -> None:
    """Item (and unit) field values; `attrs_line` joins those marked `show_on_label`."""
    specs = await effective_fields(db, item.category_id)
    line: list[str] = []
    for scope, values in (("item", item.attrs), ("unit", unit_attrs)):
        if values is None:
            continue
        scoped = [s for s in specs if s.scope == scope]
        shown = _add_values(ctx, ("attrs",), scoped, values)
        line += [shown[s.key] for s in scoped if s.show_on_label and s.key in shown]
    ctx["attrs_line"] = LINE_SEPARATOR.join(line)


async def _fill_latest(
    db: AsyncSession, ctx: dict[str, Any], *, unit_id: int | None, item: Item
) -> None:
    """`latest.<type_key>.<field>` and the unit `summary_line` from the newest log entries.

    Summary rule: the nearest category's log type (own category first, then ancestors) that
    defines `summary_fields` and has an entry supplies the line, as its summary values (in
    `summary_fields` order, values only) joined with " · ". Without one the line falls back
    to `attrs_line`.
    """
    if unit_id is not None:
        view, key = _UNIT_LATEST, _UNIT_LATEST.c.unit_id == unit_id
    else:
        view, key = _ITEM_LATEST, _ITEM_LATEST.c.item_id == item.id
    rows = (
        await db.execute(select(view.c.type_key, view.c.log_entry_type_id, _VALUES).where(key))
    ).all()
    latest = {r.log_entry_type_id: r.values for r in rows}
    shown_by_type: dict[int, list[str]] = {}
    log_types = await effective_log_types(db, item.category_id)
    for log_type in log_types:
        values = latest.get(log_type.id)
        if values is None:
            continue
        specs = [FieldSpec.from_dict(f) for f in log_type.fields]
        shown = _add_values(ctx, ("latest", log_type.key), specs, values)
        shown_by_type[log_type.id] = [shown[k] for k in log_type.summary_fields if k in shown]
    for log_type in reversed(log_types):  # nearest category first
        if shown_by_type.get(log_type.id):
            ctx["summary_line"] = LINE_SEPARATOR.join(shown_by_type[log_type.id])
            return
    ctx["summary_line"] = ctx["attrs_line"]


async def _fill_location(db: AsyncSession, ctx: dict[str, Any], location_id: int | None) -> None:
    if location_id is None:
        return
    chain = await location_path(db, location_id)
    if chain:
        ctx["location"] = {
            "name": chain[-1].name,
            "code": chain[-1].code,
            "path": PATH_SEPARATOR.join(c.name for c in chain),
        }


def _load_photo(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("L")
        image.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX))
        return image
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


async def _fill_photo(
    db: AsyncSession, ctx: dict[str, Any], source: str, attachment_id: int | None, root: Path | None
) -> None:
    if attachment_id is None or root is None:
        return
    att = await db.get(Attachment, attachment_id)
    if att is None or not att.storage_path:
        return
    photo = await asyncio.to_thread(_load_photo, attachment_path(att, root=root))
    if photo is not None:
        ctx["_images"][source] = photo


async def item_context(
    db: AsyncSession, item_id: int, *, attachments_root: Path | None = None
) -> dict[str, Any]:
    item = await get_item(db, item_id)
    ctx = _new_context()
    ctx.update(
        name=item.name,
        sku=item.sku,
        code=item.sku,
        description=item.description or "",
        category=(await get_category(db, item.category_id)).name,
    )
    await _fill_attrs(db, ctx, item, None)
    await _fill_latest(db, ctx, unit_id=None, item=item)
    await _fill_location(db, ctx, item.default_location_id)
    await _fill_photo(db, ctx, "item_photo", item.photo_attachment_id, attachments_root)
    return ctx


async def unit_context(
    db: AsyncSession, unit_id: int, *, attachments_root: Path | None = None
) -> dict[str, Any]:
    unit = await get_unit(db, unit_id)
    item = await get_item(db, unit.item_id)
    ctx = _new_context()
    ctx.update(
        name=item.name,
        sku=item.sku,
        unit_code=unit.unit_code,
        code=unit.unit_code,
        serial_number=unit.serial_number or "",
        description=item.description or "",
        category=(await get_category(db, item.category_id)).name,
    )
    await _fill_attrs(db, ctx, item, unit.attrs)
    await _fill_latest(db, ctx, unit_id=unit.id, item=item)
    await _fill_location(db, ctx, unit.location_id)
    await _fill_photo(db, ctx, "item_photo", item.photo_attachment_id, attachments_root)
    return ctx


async def location_context(
    db: AsyncSession, location_id: int, *, attachments_root: Path | None = None
) -> dict[str, Any]:
    location: Location = await get_location(db, location_id)
    ctx = _new_context()
    ctx.update(name=location.name, code=location.code, description=location.notes or "")
    await _fill_location(db, ctx, location.id)
    await _fill_photo(db, ctx, "location_photo", location.photo_attachment_id, attachments_root)
    return ctx
