"""Search with field, latest-value, location and stock filters (spec §4.4)."""

import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Numeric,
    and_,
    case,
    cast,
    column,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    table,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from pick2light.core import categories as cats
from pick2light.core import si
from pick2light.core.barcodes import lookup_barcode
from pick2light.core.fields import FieldSpec, display_values
from pick2light.core.locations import LocationRef, subtree_ids
from pick2light.core.stock import on_hand_expr
from pick2light.errors import ValidationFailed
from pick2light.models import Category, FieldDefinition, Item, Location, LogEntryType, Stock, Unit

Op = Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in"]
ACTIVE = ("in_stock", "checked_out")

unit_latest = table("unit_latest_values", column("unit_id"), column("type_key"), column("values", JSONB))
item_latest = table("item_latest_values", column("item_id"), column("type_key"), column("values", JSONB))


class FieldFilter(BaseModel):
    key: str
    op: Op = "eq"
    value: Any = None


class LatestFilter(BaseModel):
    log_type: str
    key: str
    op: Op = "eq"
    value: Any = None


class SearchQuery(BaseModel):
    q: str | None = None
    category_id: int | None = None
    include_subcategories: bool = True
    location_id: int | None = None
    conditions: list[str] = []
    filters: list[FieldFilter] = []
    latest: list[LatestFilter] = []
    low_stock: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SearchHit(BaseModel):
    id: int
    name: str
    sku: str
    category_id: int
    category_name: str
    on_hand: float
    min_stock: int | None
    attrs_display: dict[str, str]
    matched_unit_id: int | None = None
    rank: float


class SearchPage(BaseModel):
    hits: list[SearchHit]
    total: int
    location_match: LocationRef | None = None


def normalize_query(q: str) -> str:
    return unicodedata.normalize("NFKC", q).replace("μ", "u").replace("µ", "u").strip()


# ---------------------------------------------------------------- JSON predicates


def _num(col: Any, key: str) -> ColumnElement:
    return case((func.jsonb_typeof(col[key]) == "number", cast(col[key].astext, Numeric)), else_=None)


def _coerce_number(spec: FieldSpec | None, value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValidationFailed({field: "Must be a number"})
    if isinstance(value, int | float):
        return float(value)
    try:
        return si.parse_quantity(str(value), spec.number_unit if spec else None)
    except ValueError as exc:
        raise ValidationFailed({field: str(exc)}) from None


def _predicate(col: Any, key: str, spec: FieldSpec | None, op: str, value: Any, field: str) -> ColumnElement:
    is_number = spec is not None and spec.type == "number"
    if is_number and op in ("eq", "ne", "lt", "lte", "gt", "gte", "in"):
        expr = _num(col, key)
        if op == "in":
            values = value if isinstance(value, list) else [value]
            return expr.in_([_coerce_number(spec, v, field) for v in values])
        n = _coerce_number(spec, value, field)
        return {
            "eq": expr == n,
            "ne": expr != n,
            "lt": expr < n,
            "lte": expr <= n,
            "gt": expr > n,
            "gte": expr >= n,
        }[op]
    if op == "contains":
        if spec is not None and spec.type == "multi_select":
            return col[key].contains([value])
        return col[key].astext.ilike(f"%{value}%")
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return col[key].astext.in_([str(v) for v in values])
    if op in ("eq", "ne"):
        if spec is not None and spec.type == "multi_select":
            cond = col[key].contains([value])
        elif isinstance(value, bool):
            cond = col.contains({key: value})
        else:
            cond = col[key].astext == str(value)
        return cond if op == "eq" else or_(~cond, col[key].is_(None))
    if op in ("lt", "lte", "gt", "gte"):
        text = col[key].astext
        return {
            "lt": text < str(value),
            "lte": text <= str(value),
            "gt": text > str(value),
            "gte": text >= str(value),
        }[op]
    raise ValidationFailed({field: f"Unsupported operator {op}"})


async def _field_spec(db: AsyncSession, key: str, category_id: int | None) -> FieldSpec | None:
    if category_id is not None:
        for spec in await cats.effective_fields(db, category_id):
            if spec.key == key:
                return spec
    fd = await db.scalar(
        select(FieldDefinition).where(FieldDefinition.key == key).order_by(FieldDefinition.id).limit(1)
    )
    return FieldSpec.from_definition(fd) if fd else None


async def _log_type(db: AsyncSession, key: str) -> LogEntryType | None:
    return await db.scalar(
        select(LogEntryType)
        .where(LogEntryType.key == key, LogEntryType.deleted_at.is_(None))
        .order_by(LogEntryType.id)
        .limit(1)
    )


# ---------------------------------------------------------------- search


async def search(db: AsyncSession, query: SearchQuery) -> SearchPage:
    where: list[ColumnElement] = [Item.deleted_at.is_(None)]
    unit_conds: list[ColumnElement] = []
    rank: ColumnElement = literal(0.0)
    barcode_item: int | None = None
    barcode_unit: int | None = None
    location_match: LocationRef | None = None

    if query.q and query.q.strip():
        raw = query.q.strip()
        qn = normalize_query(raw)
        bc = await lookup_barcode(db, raw)
        if bc is not None:
            if bc.target_type == "item":
                barcode_item = bc.target_id
            elif bc.target_type == "unit":
                unit = await db.get(Unit, bc.target_id)
                if unit is not None:
                    barcode_item, barcode_unit = unit.item_id, unit.id
            elif bc.target_type == "location":
                loc = await db.get(Location, bc.target_id)
                if loc is not None and loc.deleted_at is None:
                    location_match = LocationRef(id=loc.id, name=loc.name, code=loc.code)
        tsq = func.websearch_to_tsquery("simple", qn.lower())
        text_match: list[ColumnElement] = [Item.search_vector.op("@@")(tsq), Item.sku.ilike(qn + "%")]
        sim: ColumnElement = literal(0.0)
        if len(qn) >= 3:
            sim = func.word_similarity(qn, Item.name)
            text_match.append(sim > 0.5)
        if barcode_item is not None:
            text_match.append(Item.id == barcode_item)
        where.append(or_(*text_match))
        rank = func.ts_rank(Item.search_vector, tsq) + sim
        if barcode_item is not None:
            rank = rank + case((Item.id == barcode_item, 1000.0), else_=0.0)
        if location_match is not None and barcode_item is None:
            where.append(false())

    if query.category_id is not None:
        ids = (
            await cats.descendant_ids(db, query.category_id)
            if query.include_subcategories
            else [(await cats.get_category(db, query.category_id)).id]
        )
        where.append(Item.category_id.in_(ids))

    if query.location_id is not None:
        loc_ids = await subtree_ids(db, query.location_id)
        in_stock = exists().where(
            Stock.item_id == Item.id, Stock.location_id.in_(loc_ids), Stock.quantity > 0
        )
        in_units = exists().where(
            Unit.item_id == Item.id,
            Unit.location_id.in_(loc_ids),
            Unit.deleted_at.is_(None),
            Unit.status.in_(ACTIVE),
        )
        where.append(or_(in_stock, in_units))

    if query.conditions:
        unit_conds.append(Unit.condition.in_(query.conditions))

    for i, f in enumerate(query.filters):
        spec = await _field_spec(db, f.key, query.category_id)
        field = f"filters.{i}.value"
        if spec is not None and spec.scope == "unit":
            unit_conds.append(_predicate(Unit.attrs, f.key, spec, f.op, f.value, field))
        else:
            where.append(_predicate(Item.attrs, f.key, spec, f.op, f.value, field))

    for i, lf in enumerate(query.latest):
        lt = await _log_type(db, lf.log_type)
        if lt is None:
            raise ValidationFailed({f"latest.{i}.log_type": f"Unknown log type {lf.log_type}"})
        spec = next((FieldSpec.from_dict(d) for d in lt.fields if d.get("key") == lf.key), None)
        field = f"latest.{i}.value"
        if lt.applies_to == "unit":
            unit_conds.append(
                exists().where(
                    unit_latest.c.unit_id == Unit.id,
                    unit_latest.c.type_key == lt.key,
                    _predicate(unit_latest.c["values"], lf.key, spec, lf.op, lf.value, field),
                )
            )
        else:
            where.append(
                exists().where(
                    item_latest.c.item_id == Item.id,
                    item_latest.c.type_key == lt.key,
                    _predicate(item_latest.c["values"], lf.key, spec, lf.op, lf.value, field),
                )
            )

    matched_unit: ColumnElement = literal(None)
    if unit_conds:
        base = [Unit.item_id == Item.id, Unit.deleted_at.is_(None), Unit.status.in_(ACTIVE), *unit_conds]
        where.append(exists().where(*base))
        matched_unit = select(func.min(Unit.id)).where(*base).scalar_subquery()
    elif barcode_unit is not None:
        matched_unit = case((Item.id == barcode_item, barcode_unit), else_=None)

    on_hand = on_hand_expr()
    if query.low_stock:
        where.append(and_(Item.min_stock.is_not(None), on_hand < Item.min_stock))

    cond = and_(true(), *where)
    total = await db.scalar(select(func.count()).select_from(Item).where(cond)) or 0
    rows = (
        await db.execute(
            select(
                Item,
                Category.name,
                on_hand.label("on_hand"),
                matched_unit.label("matched_unit"),
                rank.label("rank"),
            )
            .join(Category, Category.id == Item.category_id)
            .where(cond)
            .order_by(rank.desc(), func.lower(Item.name), Item.id)
            .limit(query.limit)
            .offset(query.offset)
        )
    ).all()

    hits = []
    specs_cache: dict[int, list[FieldSpec]] = {}
    for item, category_name, qty, unit_id, score in rows:
        if item.category_id not in specs_cache:
            specs_cache[item.category_id] = await cats.effective_fields(db, item.category_id, scope="item")
        hits.append(
            SearchHit(
                id=item.id,
                name=item.name,
                sku=item.sku,
                category_id=item.category_id,
                category_name=category_name,
                on_hand=float(qty or 0),
                min_stock=item.min_stock,
                attrs_display=display_values(specs_cache[item.category_id], item.attrs or {}),
                matched_unit_id=unit_id,
                rank=float(score or 0),
            )
        )
    return SearchPage(hits=hits, total=int(total), location_match=location_match)
