"""Categories, inherited field definitions and log entry types (spec §3.1)."""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.fields import FieldSpec
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Category, FieldDefinition, Item, Location, LocationType, LogEntryType

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
FieldType = Literal["text", "long_text", "number", "select", "multi_select", "boolean", "date", "url", "file"]
TrackingMode = Literal["bulk", "unit"]


# ---------------------------------------------------------------- schemas


class OptionIn(BaseModel):
    value: str = Field(min_length=1, max_length=100)
    label: str | None = None
    sku_code: str | None = Field(default=None, max_length=40)


class FieldDefIn(BaseModel):
    key: str
    label: str | None = None
    type: FieldType
    scope: Literal["item", "unit"] = "item"
    required: bool = False
    filterable: bool = False
    show_on_label: bool = False
    number_unit: str | None = Field(default=None, max_length=16)
    number_si_prefixes: bool = False
    min: float | None = None
    max: float | None = None
    decimals: int | None = Field(default=None, ge=0, le=12)
    options: list[OptionIn] = []
    help_text: str | None = None
    order: int | None = None


class FieldDefPatch(BaseModel):
    label: str | None = None
    type: FieldType | None = None
    scope: Literal["item", "unit"] | None = None
    required: bool | None = None
    filterable: bool | None = None
    show_on_label: bool | None = None
    number_unit: str | None = None
    number_si_prefixes: bool | None = None
    min: float | None = None
    max: float | None = None
    decimals: int | None = Field(default=None, ge=0, le=12)
    options: list[OptionIn] | None = None
    help_text: str | None = None
    order: int | None = None


class FieldDefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    key: str
    label: str
    type: str
    scope: str
    required: bool
    filterable: bool
    show_on_label: bool
    number_unit: str | None
    number_si_prefixes: bool
    min: float | None
    max: float | None
    decimals: int | None
    options: list[dict]
    help_text: str | None
    order: int
    inherited_from: int | None = None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    icon: str | None = None
    description: str | None = None
    tracking_mode: TrackingMode | None = None
    sku_prefix: str | None = Field(default=None, max_length=20)
    sku_pattern: str | None = Field(default=None, max_length=200)
    unit_id_pattern: str | None = Field(default=None, max_length=200)
    fields: list[FieldDefIn] = []


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = None
    icon: str | None = None
    description: str | None = None
    tracking_mode: TrackingMode | None = None
    sku_prefix: str | None = Field(default=None, max_length=20)
    sku_pattern: str | None = Field(default=None, max_length=200)
    unit_id_pattern: str | None = Field(default=None, max_length=200)
    default_label_template_id: int | None = None
    default_unit_label_template_id: int | None = None


class PathRef(BaseModel):
    id: int
    name: str


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    icon: str | None
    description: str | None
    tracking_mode: str | None
    effective_tracking_mode: str
    sku_prefix: str | None
    sku_pattern: str | None
    unit_id_pattern: str | None
    default_label_template_id: int | None
    default_unit_label_template_id: int | None
    path: list[PathRef]
    created_at: datetime
    updated_at: datetime


class LogEntryTypeIn(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = None
    applies_to: Literal["unit", "item"] = "unit"
    fields: list[FieldDefIn] = []
    summary_fields: list[str] = []


class LogEntryTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = None
    fields: list[FieldDefIn] | None = None
    summary_fields: list[str] | None = None


class LogEntryTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    key: str
    name: str
    icon: str | None
    applies_to: str
    fields: list[dict]
    summary_fields: list[str]
    inherited_from: int | None = None


class LocationTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = None


class LocationTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = None


class LocationTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str | None


# ---------------------------------------------------------------- tree helpers


async def _all(db: AsyncSession) -> dict[int, Category]:
    rows = await db.scalars(select(Category).where(Category.deleted_at.is_(None)))
    return {c.id: c for c in rows}


async def get_category(db: AsyncSession, category_id: int) -> Category:
    cat = await db.get(Category, category_id)
    if cat is None or cat.deleted_at is not None:
        raise NotFound(f"Category {category_id} not found")
    return cat


def _chain(cats: dict[int, Category], category_id: int) -> list[Category]:
    chain: list[Category] = []
    current: int | None = category_id
    while current is not None and current in cats:
        chain.append(cats[current])
        current = cats[current].parent_id
    return list(reversed(chain))


def _descendants(cats: dict[int, Category], category_id: int) -> list[int]:
    children: dict[int | None, list[int]] = {}
    for c in cats.values():
        children.setdefault(c.parent_id, []).append(c.id)
    out, stack = [], [category_id]
    while stack:
        cid = stack.pop()
        out.append(cid)
        stack.extend(children.get(cid, []))
    return out


def _mode(chain: list[Category]) -> str:
    for c in reversed(chain):
        if c.tracking_mode:
            return c.tracking_mode
    return "bulk"


async def ancestors(db: AsyncSession, category_id: int) -> list[Category]:
    await get_category(db, category_id)
    return _chain(await _all(db), category_id)


async def descendant_ids(db: AsyncSession, category_id: int) -> list[int]:
    await get_category(db, category_id)
    return _descendants(await _all(db), category_id)


async def effective_tracking_mode(db: AsyncSession, category_id: int) -> str:
    return _mode(await ancestors(db, category_id))


async def to_out(db: AsyncSession, cat: Category, cats: dict[int, Category] | None = None) -> CategoryOut:
    cats = cats if cats is not None else await _all(db)
    chain = _chain(cats, cat.id)
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        parent_id=cat.parent_id,
        icon=cat.icon,
        description=cat.description,
        tracking_mode=cat.tracking_mode,
        effective_tracking_mode=_mode(chain),
        sku_prefix=cat.sku_prefix,
        sku_pattern=cat.sku_pattern,
        unit_id_pattern=cat.unit_id_pattern,
        default_label_template_id=cat.default_label_template_id,
        default_unit_label_template_id=cat.default_unit_label_template_id,
        path=[PathRef(id=c.id, name=c.name) for c in chain],
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


async def list_categories(db: AsyncSession) -> list[CategoryOut]:
    cats = await _all(db)
    outs = [await to_out(db, c, cats) for c in cats.values()]
    return sorted(outs, key=lambda o: [p.name.lower() for p in o.path])


# ---------------------------------------------------------------- key rules


async def _field_keys(db: AsyncSession, category_ids: list[int]) -> set[str]:
    if not category_ids:
        return set()
    rows = await db.scalars(select(FieldDefinition.key).where(FieldDefinition.category_id.in_(category_ids)))
    return set(rows)


async def _log_type_keys(db: AsyncSession, category_ids: list[int]) -> set[str]:
    if not category_ids:
        return set()
    rows = await db.scalars(
        select(LogEntryType.key).where(
            LogEntryType.category_id.in_(category_ids), LogEntryType.deleted_at.is_(None)
        )
    )
    return set(rows)


def _related_ids(cats: dict[int, Category], category_id: int) -> list[int]:
    """Ancestors and descendants (including self): the set a key must be unique across."""
    return list({c.id for c in _chain(cats, category_id)} | set(_descendants(cats, category_id)))


def _check_key(key: str, errors: dict[str, str], name: str = "key") -> None:
    if not KEY_RE.match(key):
        errors[name] = "Use lowercase letters, digits and _ (start with a letter)"


def _validate_field_def(data: FieldDefIn | FieldDefOut, mode: str, errors: dict[str, str]) -> None:
    if data.type in ("select", "multi_select"):
        values = [o.value if isinstance(o, OptionIn) else o["value"] for o in data.options]
        if not values:
            errors["options"] = "Add at least one option"
        elif len(values) != len(set(values)):
            errors["options"] = "Option values must be unique"
    if data.scope == "unit" and mode != "unit":
        errors["scope"] = "Per-unit fields need a category tracked per unit"
    if data.min is not None and data.max is not None and data.min > data.max:
        errors["min"] = "Minimum is larger than maximum"


def _label_for(key: str) -> str:
    return key.replace("_", " ").capitalize()


# ---------------------------------------------------------------- categories


async def _has_items(db: AsyncSession, category_ids: list[int]) -> bool:
    """Whether any non-deleted item belongs to these categories."""
    count = await db.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.category_id.in_(category_ids), Item.deleted_at.is_(None))
    )
    return bool(count)


async def _check_mode_change(db: AsyncSession, subtree: list[int], new_mode: str) -> None:
    if await _has_items(db, subtree):
        raise Conflict("This category has items; its tracking mode can't change")
    if new_mode == "bulk":
        unit_fields = await db.scalar(
            select(func.count())
            .select_from(FieldDefinition)
            .where(FieldDefinition.category_id.in_(subtree), FieldDefinition.scope == "unit")
        )
        unit_logs = await db.scalar(
            select(func.count())
            .select_from(LogEntryType)
            .where(
                LogEntryType.category_id.in_(subtree),
                LogEntryType.applies_to == "unit",
                LogEntryType.deleted_at.is_(None),
            )
        )
        if unit_fields or unit_logs:
            raise Conflict("Per-unit fields or log types exist; remove them before switching to bulk")


async def create_category(db: AsyncSession, data: CategoryIn) -> Category:
    if data.parent_id is not None:
        await get_category(db, data.parent_id)
    cat = Category(
        name=data.name.strip(),
        parent_id=data.parent_id,
        icon=data.icon,
        description=data.description,
        tracking_mode=data.tracking_mode,
        sku_prefix=data.sku_prefix,
        sku_pattern=data.sku_pattern,
        unit_id_pattern=data.unit_id_pattern,
    )
    db.add(cat)
    await db.flush()
    for f in data.fields:
        await add_field(db, cat.id, f)
    return cat


async def update_category(db: AsyncSession, category_id: int, data: CategoryPatch) -> Category:
    cat = await get_category(db, category_id)
    sent = data.model_fields_set
    cats = await _all(db)
    subtree = _descendants(cats, cat.id)

    if "parent_id" in sent and data.parent_id != cat.parent_id:
        new_parent = data.parent_id
        if new_parent is not None:
            await get_category(db, new_parent)
            if new_parent in subtree:
                raise Conflict("A category can't be moved inside itself")
            new_chain_ids = [c.id for c in _chain(cats, new_parent)]
        else:
            new_chain_ids = []
        subtree_keys = await _field_keys(db, subtree)
        clash = subtree_keys & await _field_keys(db, new_chain_ids)
        if clash:
            raise Conflict(f"Field key '{sorted(clash)[0]}' already exists in the new parent")
        log_clash = await _log_type_keys(db, subtree) & await _log_type_keys(db, new_chain_ids)
        if log_clash:
            raise Conflict(f"Log type '{sorted(log_clash)[0]}' already exists in the new parent")
        old_mode = _mode(_chain(cats, cat.id))
        new_mode = cat.tracking_mode or (_mode(_chain(cats, new_parent)) if new_parent else "bulk")
        if new_mode != old_mode:
            await _check_mode_change(db, subtree, new_mode)
        cat.parent_id = new_parent

    if "tracking_mode" in sent and data.tracking_mode != cat.tracking_mode:
        old_mode = _mode(_chain(cats, cat.id))
        parent_mode = _mode(_chain(cats, cat.parent_id)) if cat.parent_id else "bulk"
        new_mode = data.tracking_mode or parent_mode
        if new_mode != old_mode:
            await _check_mode_change(db, subtree, new_mode)
        cat.tracking_mode = data.tracking_mode

    for attr in (
        "name",
        "icon",
        "description",
        "sku_prefix",
        "sku_pattern",
        "unit_id_pattern",
        "default_label_template_id",
        "default_unit_label_template_id",
    ):
        if attr in sent:
            value = getattr(data, attr)
            if attr == "name":
                if not value:
                    raise ValidationFailed({"name": "Name is required"})
                value = value.strip()
            setattr(cat, attr, value)
    await db.flush()
    return cat


async def delete_category(db: AsyncSession, category_id: int) -> None:
    cat = await get_category(db, category_id)
    children = await db.scalar(
        select(func.count())
        .select_from(Category)
        .where(Category.parent_id == cat.id, Category.deleted_at.is_(None))
    )
    if children:
        raise Conflict(f"'{cat.name}' has subcategories; move or delete them first")
    if await _has_items(db, [cat.id]):
        raise Conflict(f"'{cat.name}' still has items; move or delete them first")
    cat.deleted_at = datetime.now(UTC)
    await db.flush()


# ---------------------------------------------------------------- fields


async def effective_field_defs(db: AsyncSession, category_id: int) -> list[FieldDefinition]:
    chain = await ancestors(db, category_id)
    depth = {c.id: i for i, c in enumerate(chain)}
    rows = list(await db.scalars(select(FieldDefinition).where(FieldDefinition.category_id.in_(list(depth)))))
    return sorted(rows, key=lambda f: (depth[f.category_id], f.order, f.id))


async def field_defs_out(db: AsyncSession, category_id: int) -> list[FieldDefOut]:
    out = []
    for fd in await effective_field_defs(db, category_id):
        o = FieldDefOut.model_validate(fd)
        o.inherited_from = fd.category_id if fd.category_id != category_id else None
        out.append(o)
    return out


async def get_field(db: AsyncSession, field_id: int) -> FieldDefinition:
    fd = await db.get(FieldDefinition, field_id)
    if fd is None:
        raise NotFound(f"Field {field_id} not found")
    return fd


async def add_field(db: AsyncSession, category_id: int, data: FieldDefIn) -> FieldDefinition:
    await get_category(db, category_id)
    cats = await _all(db)
    errors: dict[str, str] = {}
    _check_key(data.key, errors)
    _validate_field_def(data, _mode(_chain(cats, category_id)), errors)
    if errors:
        raise ValidationFailed(errors)
    if data.key in await _field_keys(db, _related_ids(cats, category_id)):
        raise Conflict(f"Field key '{data.key}' already exists in this category family")
    order = data.order
    if order is None:
        current = await db.scalar(
            select(func.max(FieldDefinition.order)).where(FieldDefinition.category_id == category_id)
        )
        order = (current if current is not None else -1) + 1
    fd = FieldDefinition(
        category_id=category_id,
        key=data.key,
        label=data.label or _label_for(data.key),
        help_text=data.help_text,
        order=order,
        type=data.type,
        scope=data.scope,
        required=data.required,
        filterable=data.filterable,
        show_on_label=data.show_on_label,
        number_unit=data.number_unit,
        number_si_prefixes=data.number_si_prefixes,
        min=data.min,
        max=data.max,
        decimals=data.decimals,
        options=[o.model_dump() for o in data.options],
    )
    db.add(fd)
    await db.flush()
    return fd


async def update_field(db: AsyncSession, field_id: int, data: FieldDefPatch) -> FieldDefinition:
    fd = await get_field(db, field_id)
    for attr in data.model_fields_set:
        value = getattr(data, attr)
        if attr == "options":
            value = [o.model_dump() for o in (value or [])]
        if attr in ("type", "scope", "order", "label") and value is None:
            continue
        setattr(fd, attr, value)
    errors: dict[str, str] = {}
    candidate = FieldDefOut.model_validate(fd)
    _validate_field_def(candidate, await effective_tracking_mode(db, fd.category_id), errors)
    if errors:
        raise ValidationFailed(errors)
    await db.flush()
    return fd


async def delete_field(db: AsyncSession, field_id: int) -> None:
    """Remove the definition only; stored values stay in item/unit attrs (hidden)."""
    fd = await get_field(db, field_id)
    await db.delete(fd)
    await db.flush()


# ---------------------------------------------------------------- log entry types


def _validate_log_type(fields: list[FieldDefIn], summary: list[str], errors: dict[str, str]) -> None:
    keys = [f.key for f in fields]
    for i, f in enumerate(fields):
        sub: dict[str, str] = {}
        _check_key(f.key, sub)
        _validate_field_def(f.model_copy(update={"scope": "item"}), "unit", sub)
        for k, v in sub.items():
            errors[f"fields.{i}.{k}"] = v
    if len(keys) != len(set(keys)):
        errors["fields"] = "Field keys must be unique"
    missing = [s for s in summary if s not in keys]
    if missing:
        errors["summary_fields"] = f"Unknown field: {missing[0]}"


def _field_dicts(fields: list[FieldDefIn]) -> list[dict]:
    out = []
    for i, f in enumerate(fields):
        d = f.model_dump(exclude={"scope"})
        d["label"] = f.label or _label_for(f.key)
        d["order"] = f.order if f.order is not None else i
        out.append(d)
    return out


async def get_log_type(db: AsyncSession, log_type_id: int) -> LogEntryType:
    lt = await db.get(LogEntryType, log_type_id)
    if lt is None or lt.deleted_at is not None:
        raise NotFound(f"Log entry type {log_type_id} not found")
    return lt


async def create_log_type(db: AsyncSession, category_id: int, data: LogEntryTypeIn) -> LogEntryType:
    await get_category(db, category_id)
    cats = await _all(db)
    errors: dict[str, str] = {}
    _check_key(data.key, errors)
    _validate_log_type(data.fields, data.summary_fields, errors)
    if data.applies_to == "unit" and _mode(_chain(cats, category_id)) != "unit":
        errors["applies_to"] = "Per-unit log types need a category tracked per unit"
    if errors:
        raise ValidationFailed(errors)
    if data.key in await _log_type_keys(db, _related_ids(cats, category_id)):
        raise Conflict(f"Log type '{data.key}' already exists in this category family")
    lt = LogEntryType(
        category_id=category_id,
        key=data.key,
        name=data.name,
        icon=data.icon,
        applies_to=data.applies_to,
        fields=_field_dicts(data.fields),
        summary_fields=data.summary_fields,
    )
    db.add(lt)
    await db.flush()
    return lt


async def update_log_type(db: AsyncSession, log_type_id: int, data: LogEntryTypePatch) -> LogEntryType:
    lt = await get_log_type(db, log_type_id)
    fields = data.fields if data.fields is not None else [FieldDefIn(**f) for f in lt.fields]
    summary = data.summary_fields if data.summary_fields is not None else list(lt.summary_fields)
    errors: dict[str, str] = {}
    _validate_log_type(fields, summary, errors)
    if errors:
        raise ValidationFailed(errors)
    if data.name is not None:
        lt.name = data.name
    if "icon" in data.model_fields_set:
        lt.icon = data.icon
    lt.fields = _field_dicts(fields)
    lt.summary_fields = summary
    await db.flush()
    return lt


async def delete_log_type(db: AsyncSession, log_type_id: int) -> None:
    lt = await get_log_type(db, log_type_id)
    lt.deleted_at = datetime.now(UTC)
    await db.flush()


async def effective_log_types(db: AsyncSession, category_id: int) -> list[LogEntryType]:
    chain = await ancestors(db, category_id)
    depth = {c.id: i for i, c in enumerate(chain)}
    rows = list(
        await db.scalars(
            select(LogEntryType).where(
                LogEntryType.category_id.in_(list(depth)), LogEntryType.deleted_at.is_(None)
            )
        )
    )
    return sorted(rows, key=lambda t: (depth[t.category_id], t.name.lower()))


async def log_types_out(db: AsyncSession, category_id: int) -> list[LogEntryTypeOut]:
    out = []
    for lt in await effective_log_types(db, category_id):
        o = LogEntryTypeOut.model_validate(lt)
        o.inherited_from = lt.category_id if lt.category_id != category_id else None
        out.append(o)
    return out


# ---------------------------------------------------------------- location types


async def list_location_types(db: AsyncSession) -> list[LocationType]:
    return list(await db.scalars(select(LocationType).order_by(func.lower(LocationType.name))))


async def get_location_type(db: AsyncSession, type_id: int) -> LocationType:
    lt = await db.get(LocationType, type_id)
    if lt is None:
        raise NotFound(f"Location type {type_id} not found")
    return lt


async def _location_type_name_taken(db: AsyncSession, name: str, exclude_id: int | None = None) -> bool:
    q = select(LocationType.id).where(func.lower(LocationType.name) == name.lower())
    if exclude_id is not None:
        q = q.where(LocationType.id != exclude_id)
    return (await db.scalar(q)) is not None


async def create_location_type(db: AsyncSession, data: LocationTypeIn) -> LocationType:
    name = data.name.strip()
    if await _location_type_name_taken(db, name):
        raise Conflict(f"Location type '{name}' already exists")
    lt = LocationType(name=name, icon=data.icon)
    db.add(lt)
    await db.flush()
    return lt


async def update_location_type(db: AsyncSession, type_id: int, data: LocationTypePatch) -> LocationType:
    lt = await get_location_type(db, type_id)
    if data.name is not None:
        name = data.name.strip()
        if await _location_type_name_taken(db, name, exclude_id=lt.id):
            raise Conflict(f"Location type '{name}' already exists")
        lt.name = name
    if "icon" in data.model_fields_set:
        lt.icon = data.icon
    await db.flush()
    return lt


async def delete_location_type(db: AsyncSession, type_id: int) -> None:
    lt = await get_location_type(db, type_id)
    used = await db.scalar(
        select(func.count())
        .select_from(Location)
        .where(Location.location_type_id == lt.id, Location.deleted_at.is_(None))
    )
    if used:
        raise Conflict(f"'{lt.name}' is used by {used} location(s)")
    await db.delete(lt)
    await db.flush()


async def effective_fields(db: AsyncSession, category_id: int, scope: str | None = None) -> list[FieldSpec]:
    specs = [FieldSpec.from_definition(fd) for fd in await effective_field_defs(db, category_id)]
    return [s for s in specs if scope is None or s.scope == scope]
