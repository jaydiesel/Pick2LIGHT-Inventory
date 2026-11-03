"""Label layout schema, template strings and context builders (spec §8.1)."""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core import si
from pick2light.core.fields import display_values
from pick2light.core.items import get_item
from pick2light.core.locations import get_location, location_path
from pick2light.core.logs import latest_values
from pick2light.core.units import get_unit
from pick2light.models import LocationType, Stock

PATH_SEP = " › "
Target = Literal["item", "unit", "location", "command"]


class BarcodeEl(BaseModel):
    type: Literal["barcode"]
    symbology: Literal["qr", "datamatrix", "code128", "ean13"] = "qr"
    value: str
    x: float
    y: float
    size: float | None = None
    width: float | None = None
    height: float | None = None


class TextEl(BaseModel):
    type: Literal["text"]
    value: str
    x: float
    y: float
    w: float
    h: float
    font_size: float = 10
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    max_lines: int = Field(default=1, ge=1, le=10)


class ImageEl(BaseModel):
    type: Literal["image"]
    source: Literal["item_photo", "location_photo"] = "item_photo"
    x: float
    y: float
    w: float
    h: float


class LineEl(BaseModel):
    type: Literal["line"]
    x: float
    y: float
    w: float
    h: float = 0
    thickness: float = 0.3


class BoxEl(BaseModel):
    type: Literal["box"]
    x: float
    y: float
    w: float
    h: float
    thickness: float = 0.3


Element = Annotated[BarcodeEl | TextEl | ImageEl | LineEl | BoxEl, Field(discriminator="type")]
LAYOUT = TypeAdapter(list[Element])


class LabelTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    width_mm: float = Field(gt=0, le=300)
    height_mm: float = Field(gt=0, le=300)
    dpi: int = Field(default=203, ge=72, le=600)
    target: Target
    layout: list[Element] = []


class LabelTemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    width_mm: float | None = Field(default=None, gt=0, le=300)
    height_mm: float | None = Field(default=None, gt=0, le=300)
    dpi: int | None = Field(default=None, ge=72, le=600)
    layout: list[Element] | None = None


class LabelTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    width_mm: float
    height_mm: float
    dpi: int
    target: str
    layout: list[dict]


def parse_layout(layout: list[Any]) -> list[BarcodeEl | TextEl | ImageEl | LineEl | BoxEl]:
    return LAYOUT.validate_python(layout)


# ---------------------------------------------------------------- template strings

_TOKEN = re.compile(r"\{([A-Za-z0-9_.]+)(?:\|(si|upper))?\}")


def _lookup(ctx: dict, path: str) -> Any:
    value: Any = ctx
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def resolve(template: str, ctx: dict) -> str:
    """Fill `{path.to.value}` tokens; `|si` formats numbers, `|upper` upper-cases; `{{`/`}}` are literal."""
    text = template.replace("{{", "\x00").replace("}}", "\x01")

    def sub(m: re.Match[str]) -> str:
        path, flt = m.group(1), m.group(2)
        value = _lookup(ctx, path)
        if value is None or isinstance(value, dict):
            return ""
        if flt == "si" and isinstance(value, int | float) and not isinstance(value, bool):
            unit = (ctx.get("_units") or {}).get(path.rsplit(".", 1)[-1])
            return si.format_quantity(value, unit)
        out = str(value)
        return out.upper() if flt == "upper" else out

    return _TOKEN.sub(sub, text).replace("\x00", "{").replace("\x01", "}")


# ---------------------------------------------------------------- contexts


def _label_line(specs: list, attrs: dict) -> str:
    shown = [s for s in specs if s.show_on_label and s.key in attrs]
    return " · ".join(display_values(shown, attrs).values())


async def _location_ctx(db: AsyncSession, location_id: int | None) -> dict:
    if location_id is None:
        return {}
    loc = await get_location(db, location_id)
    path = await location_path(db, loc.id)
    return {"name": loc.name, "code": loc.code, "path": PATH_SEP.join(p.name for p in path)}


async def item_context(db: AsyncSession, item_id: int) -> dict:
    item = await get_item(db, item_id)
    specs = await cats.effective_fields(db, item.category_id, scope="item")
    chain = await cats.ancestors(db, item.category_id)
    first_loc = await db.scalar(
        select(Stock.location_id)
        .where(Stock.item_id == item.id, Stock.quantity > 0)
        .order_by(Stock.id)
        .limit(1)
    )
    attrs = item.attrs or {}
    return {
        "name": item.name,
        "sku": item.sku,
        "code": item.sku,
        "description": item.description or "",
        "category": chain[-1].name,
        "category_path": PATH_SEP.join(c.name for c in chain),
        "attrs": display_values(specs, attrs),
        "raw": dict(attrs),
        "_units": {s.key: s.number_unit for s in specs if s.number_unit},
        "label_line": _label_line(specs, attrs),
        "location": await _location_ctx(db, first_loc or item.default_location_id),
        "_photo_attachment_id": item.photo_attachment_id,
    }


async def unit_context(db: AsyncSession, unit_id: int) -> dict:
    unit = await get_unit(db, unit_id)
    item_ctx = await item_context(db, unit.item_id)
    item = await get_item(db, unit.item_id)
    unit_specs = await cats.effective_fields(db, item.category_id, scope="unit")
    latest = await latest_values(db, unit_id=unit.id)
    item_specs = await cats.effective_fields(db, item.category_id, scope="item")
    labels = [_label_line(item_specs, item.attrs or {}), _label_line(unit_specs, unit.attrs or {})]
    return {
        **item_ctx,
        "item": {"name": item.name, "sku": item.sku},
        "unit_code": unit.unit_code,
        "code": unit.unit_code,
        "serial_number": unit.serial_number or "",
        "condition": unit.condition.replace("_", " "),
        "attrs": {**item_ctx["attrs"], **display_values(unit_specs, unit.attrs or {})},
        "raw": {**item_ctx["raw"], **(unit.attrs or {})},
        "latest": {key: dict(v.values_display) for key, v in latest.items()},
        "summary_line": " · ".join(x for v in latest.values() for x in v.values_display.values()),
        "label_line": " · ".join(x for x in labels if x),
        "location": await _location_ctx(db, unit.location_id),
    }


async def location_context(db: AsyncSession, location_id: int) -> dict:
    loc = await get_location(db, location_id)
    path = await location_path(db, loc.id)
    type_name = (await db.get(LocationType, loc.location_type_id)).name if loc.location_type_id else ""  # type: ignore[union-attr]
    return {
        "name": loc.name,
        "code": loc.code,
        "path": PATH_SEP.join(p.name for p in path),
        "type": type_name,
        "notes": loc.notes or "",
        "_photo_attachment_id": loc.photo_attachment_id,
    }


async def context_for(db: AsyncSession, target_type: str, target_id: int) -> dict:
    if target_type == "item":
        return await item_context(db, target_id)
    if target_type == "unit":
        return await unit_context(db, target_id)
    return await location_context(db, target_id)
