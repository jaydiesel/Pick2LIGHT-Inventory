"""One search box plus structured filters over items.

Text matching: an exact barcode hit ranks first (1000); otherwise full text over
`item.search_text` (which carries SI spellings such as `4k7`, `4.7kΩ`, `2.2u`), trigram
word similarity on the name (typo tolerance) and a SKU prefix. Filters are ANDed on top.

Unit-level constraints (unit-scope field filters, conditions, latest unit values) must all
hold on the *same* active unit (`in_stock` / `checked_out`); the hit then names the first
such unit as `matched_unit_id`. Comparison filters (`lt`, `ne`, ...) never match an item
whose value is missing or of the wrong JSON type, so stale data cannot crash a search.
"""

import math
import operator
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Float,
    Numeric,
    and_,
    case,
    cast,
    column,
    exists,
    func,
    literal,
    or_,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from pick2light.core import si
from pick2light.core.barcodes import lookup_barcode
from pick2light.core.categories import descendant_ids, effective_fields, get_category
from pick2light.core.fields import FieldSpec, display_values
from pick2light.core.locations import LocationRef, get_location, subtree_ids
from pick2light.errors import ValidationFailed
from pick2light.models import (
    Category,
    FieldDefinition,
    Item,
    Location,
    LogEntryType,
    Stock,
    Unit,
)
from pick2light.models.inventory import UNIT_CONDITIONS

Op = Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in"]

ACTIVE_UNIT_STATUSES = ("in_stock", "checked_out")
BARCODE_RANK = 1000.0
# word_similarity(query, name): "resistr" vs "Resistor 10k" is 0.75; unrelated words stay < 0.4.
FUZZY_THRESHOLD = 0.5
FUZZY_MIN_LENGTH = 3  # shorter queries share too few trigrams to be meaningful

_COMPARE: dict[str, Callable[[Any, Any], ColumnElement[bool]]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}
_UNIT_LATEST = table("unit_latest_values", column("unit_id"), column("type_key"))
_ITEM_LATEST = table("item_latest_values", column("item_id"), column("type_key"))
_UNIT_LATEST_VALUES = column("values", JSONB)
_ITEM_LATEST_VALUES = column("values", JSONB)


class FieldFilter(BaseModel):
    key: str
    op: Op
    value: Any


class LatestFilter(BaseModel):
    log_type: str
    key: str
    op: Op
    value: Any


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
    matched_unit_id: int | None
    rank: float


class SearchPage(BaseModel):
    hits: list[SearchHit]
    total: int
    location_match: LocationRef | None = None


def normalise_query(text: str) -> str:
    """NFKC, `µ`/`μ` -> `u` (as in the indexed SI spellings), whitespace collapsed."""
    folded = unicodedata.normalize("NFKC", text).replace("μ", "u").replace("µ", "u")
    return " ".join(folded.split())


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _bad(message: str) -> ValidationFailed:
    return ValidationFailed({"filters": message})


# --------------------------------------------------------------------------- predicates


def _number(spec: FieldSpec, value: Any) -> Decimal:
    if isinstance(value, bool):
        raise _bad(f"{spec.key}: enter a number")
    if isinstance(value, str):
        try:
            parsed = si.parse_quantity(
                value, spec.number_unit, allow_prefixes=spec.number_si_prefixes
            )
        except ValueError as exc:
            raise _bad(f"{spec.key}: {exc}") from None
    elif isinstance(value, int | float):
        parsed = value
    else:
        raise _bad(f"{spec.key}: enter a number")
    if not math.isfinite(parsed):
        raise _bad(f"{spec.key}: enter a finite number")
    return Decimal(repr(parsed))


def field_predicate(json_col: Any, spec: FieldSpec, op: str, value: Any) -> ColumnElement[bool]:
    """Condition on `json_col[spec.key]` (a JSONB expression) for the field's type."""
    result: ColumnElement[bool] = _field_predicate(json_col, spec, op, value)
    return result


def _field_predicate(json_col: Any, spec: FieldSpec, op: str, value: Any) -> Any:
    raw = json_col[spec.key]
    is_list = isinstance(value, list)
    if (op == "in") != is_list:
        raise _bad(
            f"{spec.key}: {'in needs a list' if op == 'in' else op + ' needs a single value'}"
        )
    values = value if is_list else [value]

    if spec.type == "number":
        if op == "contains":
            raise _bad(f"{spec.key}: contains does not apply to numbers")
        number = case((func.jsonb_typeof(raw) == "number", cast(raw, Numeric)), else_=None)
        params = [literal(_number(spec, v), Numeric()) for v in values]
        if op == "in":
            return number.in_(params)
        return _COMPARE[op](number, params[0])

    if spec.type == "multi_select":
        if op in ("lt", "lte", "gt", "gte"):
            raise _bad(f"{spec.key}: {op} does not apply to this field")
        has = [raw.contains([str(v)]) for v in values]
        if op == "ne":
            return and_(raw.is_not(None), ~has[0])
        return or_(*has) if op == "in" else has[0]

    if spec.type == "boolean":
        if op not in ("eq", "ne") or not isinstance(values[0], bool):
            raise _bad(f"{spec.key}: use eq or ne with true or false")
        return _COMPARE[op](raw.astext, "true" if values[0] else "false")

    if spec.type in ("text", "long_text", "select", "url", "date"):
        text_value = raw.astext
        strings = [str(v) for v in values]
        if op == "contains":
            return text_value.ilike(f"%{_escape_like(strings[0])}%", escape="\\")
        if op == "in":
            return text_value.in_(strings)
        return _COMPARE[op](text_value, strings[0])

    raise _bad(f"{spec.key}: fields of type {spec.type} cannot be filtered")


UnitClause = Callable[[Any], ColumnElement[bool]]


async def _resolve_field(db: AsyncSession, key: str) -> tuple[str, FieldSpec]:
    defs = list(await db.scalars(select(FieldDefinition).where(FieldDefinition.key == key)))
    if not defs:
        raise _bad(f"unknown field {key!r}")
    scopes = {d.scope for d in defs}
    if len(scopes) > 1:
        raise _bad(f"field {key!r} is used at both item and unit level; it cannot be filtered")
    return defs[0].scope, FieldSpec.from_definition(defs[0])


async def _resolve_latest(db: AsyncSession, flt: LatestFilter) -> tuple[str, FieldSpec]:
    types = list(
        await db.scalars(
            select(LogEntryType).where(
                LogEntryType.key == flt.log_type, LogEntryType.deleted_at.is_(None)
            )
        )
    )
    if not types:
        raise _bad(f"unknown log type {flt.log_type!r}")
    if len({t.applies_to for t in types}) > 1:
        raise _bad(f"log type {flt.log_type!r} applies to both items and units")
    for log_type in types:
        for field in log_type.fields:
            if field.get("key") == flt.key:
                return log_type.applies_to, FieldSpec.from_dict(field)
    raise _bad(f"log type {flt.log_type!r} has no field {flt.key!r}")


def _unit_condition_clause(conditions: list[str]) -> UnitClause:
    def clause(u: Any) -> ColumnElement[bool]:
        result: ColumnElement[bool] = u.condition.in_(conditions)
        return result

    return clause


def _unit_field_clause(spec: FieldSpec, flt: FieldFilter) -> UnitClause:
    def clause(u: Any) -> ColumnElement[bool]:
        return field_predicate(u.attrs, spec, flt.op, flt.value)

    return clause


def _unit_latest_clause(spec: FieldSpec, lat: LatestFilter) -> UnitClause:
    def clause(u: Any) -> ColumnElement[bool]:
        return exists().where(
            _UNIT_LATEST.c.unit_id == u.id,
            _UNIT_LATEST.c.type_key == lat.log_type,
            field_predicate(_UNIT_LATEST_VALUES, spec, lat.op, lat.value),
        )

    return clause


# --------------------------------------------------------------------------- search


async def _page_attrs_display(db: AsyncSession, rows: list[Any]) -> dict[int, dict[str, str]]:
    specs_by_category: dict[int, list[FieldSpec]] = {}
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        if row.category_id not in specs_by_category:
            specs_by_category[row.category_id] = await effective_fields(
                db, row.category_id, scope="item"
            )
        out[row.id] = display_values(specs_by_category[row.category_id], row.attrs)
    return out


async def search(db: AsyncSession, query: SearchQuery) -> SearchPage:
    q = normalise_query(query.q or "")

    # --- scan codes: a location code answers with the location, no items
    barcode_item_id: int | None = None
    barcode_unit_id: int | None = None
    if q:
        barcode = await lookup_barcode(db, unicodedata.normalize("NFKC", query.q or ""))
        if barcode is not None:
            if barcode.target_type == "location":
                location = await db.get(Location, barcode.target_id)
                if location is not None and location.deleted_at is None:
                    return SearchPage(
                        hits=[],
                        total=0,
                        location_match=LocationRef(
                            id=location.id, name=location.name, code=location.code
                        ),
                    )
            elif barcode.target_type == "item":
                barcode_item_id = barcode.target_id
            else:
                unit = await db.get(Unit, barcode.target_id)
                if unit is not None and unit.deleted_at is None:
                    barcode_item_id, barcode_unit_id = unit.item_id, unit.id

    # --- item-level conditions
    conds: list[ColumnElement[bool]] = [Item.deleted_at.is_(None)]
    if q:
        tsq = func.websearch_to_tsquery("simple", q)
        text_match: list[ColumnElement[bool]] = [
            Item.search_vector.op("@@")(tsq),
            Item.sku.ilike(f"{_escape_like(q)}%", escape="\\"),
        ]
        if len(q) >= FUZZY_MIN_LENGTH:
            text_match.append(func.word_similarity(q, Item.name) > FUZZY_THRESHOLD)
        if barcode_item_id is not None:
            text_match.append(Item.id == barcode_item_id)
        conds.append(or_(*text_match))
    if query.category_id is not None:
        await get_category(db, query.category_id)
        category_ids = (
            await descendant_ids(db, query.category_id)
            if query.include_subcategories
            else [query.category_id]
        )
        conds.append(Item.category_id.in_(category_ids))

    unit_clauses: list[UnitClause] = []
    if query.conditions:
        bad = [c for c in query.conditions if c not in UNIT_CONDITIONS]
        if bad:
            raise ValidationFailed({"conditions": f"unknown condition {bad[0]!r}"})
        conditions = list(query.conditions)
        unit_clauses.append(_unit_condition_clause(conditions))

    for flt in query.filters:
        scope, spec = await _resolve_field(db, flt.key)
        if scope == "unit":
            unit_clauses.append(_unit_field_clause(spec, flt))
        else:
            conds.append(field_predicate(Item.attrs, spec, flt.op, flt.value))

    for lat in query.latest:
        applies_to, spec = await _resolve_latest(db, lat)
        if applies_to == "unit":
            unit_clauses.append(_unit_latest_clause(spec, lat))
        else:
            conds.append(
                exists().where(
                    _ITEM_LATEST.c.item_id == Item.id,
                    _ITEM_LATEST.c.type_key == lat.log_type,
                    field_predicate(_ITEM_LATEST_VALUES, spec, lat.op, lat.value),
                )
            )

    location_ids: list[int] = []
    if query.location_id is not None:
        await get_location(db, query.location_id)
        location_ids = await subtree_ids(db, query.location_id)

    def unit_where(u: Any) -> ColumnElement[bool]:
        parts = [
            u.item_id == Item.id,
            u.deleted_at.is_(None),
            u.status.in_(ACTIVE_UNIT_STATUSES),
            *(clause(u) for clause in unit_clauses),
        ]
        if location_ids:
            parts.append(u.location_id.in_(location_ids))
        return and_(*parts)

    def any_unit() -> ColumnElement[bool]:
        u = aliased(Unit)
        return exists(select(literal(1)).select_from(u).where(unit_where(u)))

    if unit_clauses:
        conds.append(any_unit())
    elif location_ids:
        in_stock = exists().where(
            Stock.item_id == Item.id, Stock.location_id.in_(location_ids), Stock.quantity > 0
        )
        conds.append(or_(in_stock, any_unit()))

    bulk_qty = (
        select(func.coalesce(func.sum(Stock.quantity), 0))
        .where(Stock.item_id == Item.id)
        .scalar_subquery()
    )
    unit_qty = (
        select(func.count())
        .select_from(Unit)
        .where(Unit.item_id == Item.id, Unit.deleted_at.is_(None), Unit.status == "in_stock")
        .scalar_subquery()
    )
    on_hand = bulk_qty + unit_qty
    if query.low_stock:
        conds.append(and_(Item.min_stock.is_not(None), on_hand < Item.min_stock))

    # --- ranking and the matched unit
    rank: ColumnElement[Any]
    if q:
        text_rank = cast(
            func.ts_rank(Item.search_vector, func.websearch_to_tsquery("simple", q))
            + func.word_similarity(q, Item.name),
            Float,
        )
        rank = (
            case((Item.id == barcode_item_id, BARCODE_RANK), else_=text_rank)
            if barcode_item_id is not None
            else text_rank
        )
    else:
        rank = literal(0.0, Float())

    matched: ColumnElement[Any] = literal(None, Unit.id.type)
    if unit_clauses or location_ids or barcode_unit_id is not None:
        u2 = aliased(Unit)
        order: list[Any] = [u2.id]
        if barcode_unit_id is not None:
            order.insert(0, (u2.id != barcode_unit_id))  # prefer the scanned unit
        first_unit = select(u2.id).where(unit_where(u2)).order_by(*order).limit(1).scalar_subquery()
        matched = first_unit
        if barcode_unit_id is not None and not unit_clauses and not location_ids:
            matched = func.coalesce(
                first_unit, case((Item.id == barcode_item_id, barcode_unit_id), else_=None)
            )

    total = await db.scalar(select(func.count()).select_from(Item).where(*conds)) or 0
    rows = (
        await db.execute(
            select(
                Item.id,
                Item.name,
                Item.sku,
                Item.category_id,
                Category.name.label("category_name"),
                Item.attrs,
                Item.min_stock,
                on_hand.label("on_hand"),
                matched.label("matched_unit_id"),
                rank.label("rank"),
            )
            .join(Category, Category.id == Item.category_id)
            .where(*conds)
            .order_by(rank.desc(), Item.name, Item.id)
            .limit(query.limit)
            .offset(query.offset)
        )
    ).all()
    display = await _page_attrs_display(db, list(rows))
    hits = [
        SearchHit(
            id=r.id,
            name=r.name,
            sku=r.sku,
            category_id=r.category_id,
            category_name=r.category_name,
            on_hand=float(r.on_hand),
            min_stock=r.min_stock,
            attrs_display=display[r.id],
            matched_unit_id=r.matched_unit_id,
            rank=float(r.rank),
        )
        for r in rows
    ]
    return SearchPage(hits=hits, total=total)
