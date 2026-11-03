"""Category tree, inherited field definitions and log entry types.

Services flush but never commit; the request-scoped session commits.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.fields import FieldSpec
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.models import Category, FieldDefinition, Item, LabelTemplate, LogEntryType

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"
Key = Annotated[str, Field(pattern=KEY_PATTERN)]
TrackingMode = Literal["bulk", "unit"]
FieldType = Literal[
    "text", "long_text", "number", "select", "multi_select", "boolean", "date", "url", "file"
]
SELECT_TYPES = ("select", "multi_select")


# --------------------------------------------------------------------------- schemas


class FieldOption(BaseModel):
    value: str
    label: str
    sku_code: str | None = None


class FieldBase(BaseModel):
    """Shape shared by field definitions and the fields embedded in log entry types."""

    key: Key
    label: str = Field(min_length=1, max_length=200)
    help_text: str | None = None
    order: int = 0
    type: FieldType
    required: bool = False
    filterable: bool = False
    show_on_label: bool = False
    number_unit: str | None = None
    number_si_prefixes: bool = True
    min: float | None = None
    max: float | None = None
    decimals: int | None = Field(default=None, ge=0, le=12)
    options: list[FieldOption] | None = None


class FieldDefIn(FieldBase):
    scope: Literal["item", "unit"] = "item"


class FieldDefPatch(BaseModel):
    key: Key | None = None
    label: str | None = Field(default=None, min_length=1, max_length=200)
    help_text: str | None = None
    order: int | None = None
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
    options: list[FieldOption] | None = None


class FieldDefOut(FieldBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    scope: Literal["item", "unit"]
    inherited_from: int | None = None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    icon: str | None = None
    description: str | None = None
    tracking_mode: TrackingMode | None = None
    sku_prefix: str | None = None
    sku_pattern: str | None = None
    unit_id_pattern: str | None = None
    default_label_template_id: int | None = None
    default_unit_label_template_id: int | None = None


class CategoryPatch(BaseModel):
    """Every `CategoryIn` field, optional. Only fields present in the request are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = None
    icon: str | None = None
    description: str | None = None
    tracking_mode: TrackingMode | None = None
    sku_prefix: str | None = None
    sku_pattern: str | None = None
    unit_id_pattern: str | None = None
    default_label_template_id: int | None = None
    default_unit_label_template_id: int | None = None


class PathItem(BaseModel):
    id: int
    name: str


class CategoryOut(CategoryIn):
    id: int
    effective_tracking_mode: TrackingMode
    path: list[PathItem]


class LogEntryTypeIn(BaseModel):
    key: Key
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = None
    applies_to: Literal["unit", "item"]
    fields: list[FieldBase] = []
    summary_fields: list[str] = []


class LogEntryTypePatch(BaseModel):
    key: Key | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = None
    applies_to: Literal["unit", "item"] | None = None
    fields: list[FieldBase] | None = None
    summary_fields: list[str] | None = None


class LogEntryTypeOut(LogEntryTypeIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int


# --------------------------------------------------------------------------- tree


async def get_category(db: AsyncSession, category_id: int) -> Category:
    category = await db.get(Category, category_id)
    if category is None or category.deleted_at is not None:
        raise NotFound(f"Category {category_id} not found")
    return category


async def ancestors(db: AsyncSession, category_id: int) -> list[Category]:
    """The category's chain from the root down to and including itself."""
    chain = (
        select(Category.id, Category.parent_id, literal(0).label("depth"))
        .where(Category.id == category_id)
        .cte("chain", recursive=True)
    )
    chain = chain.union_all(
        select(Category.id, Category.parent_id, chain.c.depth + 1).join(
            chain, Category.id == chain.c.parent_id
        )
    )
    rows = await db.scalars(
        select(Category).join(chain, Category.id == chain.c.id).order_by(chain.c.depth.desc())
    )
    result = list(rows)
    if not result or result[-1].id != category_id or result[-1].deleted_at is not None:
        raise NotFound(f"Category {category_id} not found")
    return result


async def descendant_ids(db: AsyncSession, category_id: int) -> list[int]:
    """Ids of the category and all its non-deleted descendants."""
    tree = select(Category.id).where(Category.id == category_id).cte("tree", recursive=True)
    tree = tree.union_all(
        select(Category.id)
        .join(tree, Category.parent_id == tree.c.id)
        .where(Category.deleted_at.is_(None))
    )
    return list(await db.scalars(select(tree.c.id)))


def _mode_from_chain(chain: Sequence[Category]) -> TrackingMode:
    for category in reversed(chain):
        if category.tracking_mode == "unit":
            return "unit"
        if category.tracking_mode == "bulk":
            return "bulk"
    return "bulk"


async def effective_tracking_mode(db: AsyncSession, category_id: int) -> TrackingMode:
    return _mode_from_chain(await ancestors(db, category_id))


def build_category_out(category: Category, chain: Sequence[Category]) -> CategoryOut:
    """`chain` is the root-first ancestor list ending with `category`."""
    return CategoryOut(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        icon=category.icon,
        description=category.description,
        tracking_mode=category.tracking_mode,
        sku_prefix=category.sku_prefix,
        sku_pattern=category.sku_pattern,
        unit_id_pattern=category.unit_id_pattern,
        default_label_template_id=category.default_label_template_id,
        default_unit_label_template_id=category.default_unit_label_template_id,
        effective_tracking_mode=_mode_from_chain(chain),
        path=[PathItem(id=c.id, name=c.name) for c in chain],
    )


async def category_out(db: AsyncSession, category: Category) -> CategoryOut:
    return build_category_out(category, await ancestors(db, category.id))


async def list_category_outs(db: AsyncSession) -> list[CategoryOut]:
    """All non-deleted categories (name order), resolved in memory from one query."""
    categories = list(
        await db.scalars(
            select(Category)
            .where(Category.deleted_at.is_(None))
            .order_by(Category.name, Category.id)
        )
    )
    by_id = {c.id: c for c in categories}

    def chain_of(category: Category) -> list[Category]:
        chain = [category]
        while chain[0].parent_id is not None and chain[0].parent_id in by_id:
            chain.insert(0, by_id[chain[0].parent_id])
        return chain

    return [build_category_out(c, chain_of(c)) for c in categories]


async def _items_exist(db: AsyncSession, category_ids: Sequence[int]) -> bool:
    """Whether any non-deleted item belongs to one of these categories."""
    found = await db.scalar(
        select(Item.id)
        .where(Item.category_id.in_(category_ids), Item.deleted_at.is_(None))
        .limit(1)
    )
    return found is not None


async def _check_templates(db: AsyncSession, values: dict[str, Any]) -> None:
    """Default label templates must exist (the columns are foreign keys)."""
    errors = {}
    for name in ("default_label_template_id", "default_unit_label_template_id"):
        template_id = values.get(name)
        if template_id is not None and await db.get(LabelTemplate, template_id) is None:
            errors[name] = "Label template not found"
    if errors:
        raise ValidationFailed(errors)


async def create_category(db: AsyncSession, data: CategoryIn) -> Category:
    if data.parent_id is not None:
        await get_category(db, data.parent_id)
    await _check_templates(db, data.model_dump())
    category = Category(**data.model_dump())
    db.add(category)
    await db.flush()
    return category


async def update_category(db: AsyncSession, category_id: int, data: CategoryPatch) -> Category:
    category = await get_category(db, category_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise ValidationFailed({"name": "required"})
    await _check_templates(db, changes)

    moving = "parent_id" in changes and changes["parent_id"] != category.parent_id
    mode_changing = (
        "tracking_mode" in changes and changes["tracking_mode"] != category.tracking_mode
    )
    if moving:
        await _check_move(db, category, changes["parent_id"])
    if mode_changing and await _items_exist(db, await descendant_ids(db, category.id)):
        raise Conflict("Cannot change the tracking mode of a category that has items")
    if moving or mode_changing:
        await _check_unit_usage(
            db,
            category,
            new_parent_id=changes["parent_id"] if moving else category.parent_id,
            new_mode=changes["tracking_mode"] if mode_changing else category.tracking_mode,
        )

    for name, value in changes.items():
        setattr(category, name, value)
    await db.flush()
    return category


async def _subtree_modes(
    db: AsyncSession, root: Category, parent_id: int | None, root_mode: str | None
) -> dict[int, TrackingMode]:
    """Effective tracking mode of `root` and each descendant under a hypothetical parent/mode."""
    base: TrackingMode = (
        "bulk" if parent_id is None else await effective_tracking_mode(db, parent_id)
    )
    ids = await descendant_ids(db, root.id)
    rows = {c.id: c for c in await db.scalars(select(Category).where(Category.id.in_(ids)))}

    def mode_of(category: Category) -> TrackingMode:
        explicit = root_mode if category.id == root.id else category.tracking_mode
        if explicit in ("bulk", "unit"):
            return explicit  # type: ignore[return-value]
        if category.id == root.id:
            return base
        return mode_of(rows[category.parent_id])  # type: ignore[index]

    return {cid: mode_of(c) for cid, c in rows.items()}


async def _check_unit_usage(
    db: AsyncSession, category: Category, new_parent_id: int | None, new_mode: str | None
) -> None:
    """Refuse a move / mode change that turns unit-tracked categories into bulk ones
    while they still hold unit-scope fields or unit log entry types."""
    before = await _subtree_modes(db, category, category.parent_id, category.tracking_mode)
    after = await _subtree_modes(db, category, new_parent_id, new_mode)
    turning_bulk = [cid for cid, mode in after.items() if mode == "bulk" and before[cid] == "unit"]
    if not turning_bulk:
        return
    field_key = await db.scalar(
        select(FieldDefinition.key)
        .where(FieldDefinition.category_id.in_(turning_bulk), FieldDefinition.scope == "unit")
        .order_by(FieldDefinition.id)
        .limit(1)
    )
    if field_key is not None:
        raise Conflict(
            f"Unit-scope field '{field_key}' requires unit tracking; "
            "remove it before making this subtree bulk-tracked"
        )
    log_key = await db.scalar(
        _live_log_keys(turning_bulk).where(LogEntryType.applies_to == "unit").limit(1)
    )
    if log_key is not None:
        raise Conflict(
            f"Log entry type '{log_key}' applies to units; "
            "remove it before making this subtree bulk-tracked"
        )


async def _check_move(db: AsyncSession, category: Category, new_parent_id: int | None) -> None:
    subtree = await descendant_ids(db, category.id)
    if new_parent_id is None:
        return
    if new_parent_id in subtree:
        raise Conflict("A category cannot be moved into itself or one of its descendants")
    new_chain = await ancestors(db, new_parent_id)  # NotFound if missing
    chain_ids = [c.id for c in new_chain]

    moved_fields = set(
        await db.scalars(
            select(FieldDefinition.key).where(FieldDefinition.category_id.in_(subtree))
        )
    )
    inherited_fields = set(
        await db.scalars(
            select(FieldDefinition.key).where(FieldDefinition.category_id.in_(chain_ids))
        )
    )
    if clash := moved_fields & inherited_fields:
        raise Conflict(
            f"Field keys already defined above the new parent: {', '.join(sorted(clash))}"
        )

    moved_logs = set(await db.scalars(_live_log_keys(subtree)))
    inherited_logs = set(await db.scalars(_live_log_keys(chain_ids)))
    if clash := moved_logs & inherited_logs:
        raise Conflict(
            f"Log entry type keys already defined above the new parent: {', '.join(sorted(clash))}"
        )


async def delete_category(db: AsyncSession, category_id: int) -> None:
    category = await get_category(db, category_id)
    children = await db.scalar(
        select(func.count())
        .select_from(Category)
        .where(Category.parent_id == category_id, Category.deleted_at.is_(None))
    )
    if children:
        raise Conflict("Category has sub-categories")
    if await _items_exist(db, [category_id]):
        raise Conflict("Category has items")
    category.deleted_at = datetime.now(UTC)
    await db.flush()


# --------------------------------------------------------------------------- fields


def _live_log_keys(category_ids: Sequence[int]) -> Any:
    return select(LogEntryType.key).where(
        LogEntryType.category_id.in_(category_ids), LogEntryType.deleted_at.is_(None)
    )


def _check_options(type_: str, options: Sequence[Any] | None, errors: dict[str, str]) -> None:
    if type_ in SELECT_TYPES and not options:
        errors["options"] = "at least one option is required"


async def _check_field_key_free(
    db: AsyncSession, category_id: int, key: str, exclude_id: int | None = None
) -> None:
    related = [c.id for c in await ancestors(db, category_id)]
    related += await descendant_ids(db, category_id)
    query = select(FieldDefinition.id).where(
        FieldDefinition.category_id.in_(related), FieldDefinition.key == key
    )
    if exclude_id is not None:
        query = query.where(FieldDefinition.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise Conflict(
            f"Field key '{key}' is already used in this category's ancestors or descendants"
        )


async def _check_scope(db: AsyncSession, category_id: int, scope: str) -> None:
    if scope == "unit" and await effective_tracking_mode(db, category_id) != "unit":
        raise ValidationFailed({"scope": "unit scope requires a unit-tracked category"})


async def add_field(db: AsyncSession, category_id: int, data: FieldDefIn) -> FieldDefinition:
    await get_category(db, category_id)
    errors: dict[str, str] = {}
    _check_options(data.type, data.options, errors)
    if errors:
        raise ValidationFailed(errors)
    await _check_scope(db, category_id, data.scope)
    await _check_field_key_free(db, category_id, data.key)
    field = FieldDefinition(category_id=category_id, **data.model_dump())
    db.add(field)
    await db.flush()
    return field


async def get_field(db: AsyncSession, field_id: int) -> FieldDefinition:
    field = await db.get(FieldDefinition, field_id)
    if field is None:
        raise NotFound(f"Field {field_id} not found")
    return field


async def update_field(db: AsyncSession, field_id: int, data: FieldDefPatch) -> FieldDefinition:
    field = await get_field(db, field_id)
    changes = data.model_dump(exclude_unset=True)
    non_nullable = (
        "key", "label", "type", "scope", "order", "required", "filterable", "show_on_label",
        "number_si_prefixes",
    )  # fmt: skip
    for name in non_nullable:
        if name in changes and changes[name] is None:
            raise ValidationFailed({name: "must not be null"})
    errors: dict[str, str] = {}
    _check_options(changes.get("type", field.type), changes.get("options", field.options), errors)
    if errors:
        raise ValidationFailed(errors)
    if "scope" in changes:
        await _check_scope(db, field.category_id, changes["scope"])
    if "key" in changes and changes["key"] != field.key:
        await _check_field_key_free(db, field.category_id, changes["key"], exclude_id=field.id)
    for name, value in changes.items():
        setattr(field, name, value)
    await db.flush()
    return field


async def delete_field(db: AsyncSession, field_id: int) -> None:
    """Hard-delete the definition; values already stored on items/units are left alone."""
    await db.delete(await get_field(db, field_id))
    await db.flush()


async def effective_field_defs(db: AsyncSession, category_id: int) -> list[FieldDefinition]:
    """Ancestor fields first (root down), each level ordered by `order`."""
    chain = await ancestors(db, category_id)
    depth = {c.id: i for i, c in enumerate(chain)}
    rows = await db.scalars(select(FieldDefinition).where(FieldDefinition.category_id.in_(depth)))
    return sorted(rows, key=lambda f: (depth[f.category_id], f.order, f.id))


async def effective_fields(
    db: AsyncSession, category_id: int, scope: str | None = None
) -> list[FieldSpec]:
    """Effective field definitions as validation specs, optionally only one scope."""
    return [
        FieldSpec.from_definition(f)
        for f in await effective_field_defs(db, category_id)
        if scope is None or f.scope == scope
    ]


# --------------------------------------------------------------------------- log entry types


def _check_log_type(fields: Sequence[FieldBase], summary_fields: Sequence[str]) -> None:
    errors: dict[str, str] = {}
    keys = [f.key for f in fields]
    if len(set(keys)) != len(keys):
        errors["fields"] = "field keys must be unique"
    for f in fields:
        _check_options(f.type, f.options, errors)
    if not set(summary_fields) <= set(keys):
        errors["summary_fields"] = "must reference keys defined in fields"
    if errors:
        raise ValidationFailed(errors)


async def _check_log_key_free(
    db: AsyncSession, category_id: int, key: str, exclude_id: int | None = None
) -> None:
    related = [c.id for c in await ancestors(db, category_id)]
    related += await descendant_ids(db, category_id)
    query = _live_log_keys(related).where(LogEntryType.key == key)
    if exclude_id is not None:
        query = query.where(LogEntryType.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise Conflict(f"Log entry type key '{key}' is already used above or below this category")


async def create_log_type(db: AsyncSession, category_id: int, data: LogEntryTypeIn) -> LogEntryType:
    await get_category(db, category_id)
    _check_log_type(data.fields, data.summary_fields)
    await _check_log_key_free(db, category_id, data.key)
    log_type = LogEntryType(category_id=category_id, **data.model_dump())
    db.add(log_type)
    await db.flush()
    return log_type


async def get_log_type(db: AsyncSession, log_type_id: int) -> LogEntryType:
    log_type = await db.get(LogEntryType, log_type_id)
    if log_type is None or log_type.deleted_at is not None:
        raise NotFound(f"Log entry type {log_type_id} not found")
    return log_type


async def update_log_type(
    db: AsyncSession, log_type_id: int, data: LogEntryTypePatch
) -> LogEntryType:
    log_type = await get_log_type(db, log_type_id)
    changes = data.model_dump(exclude_unset=True)
    for required in ("key", "name", "applies_to", "fields", "summary_fields"):
        if required in changes and changes[required] is None:
            raise ValidationFailed({required: "required"})
    fields = (
        data.fields
        if data.fields is not None
        else [FieldBase.model_validate(f) for f in log_type.fields]
    )
    summary = changes.get("summary_fields", log_type.summary_fields)
    _check_log_type(fields, summary)
    if "key" in changes and changes["key"] != log_type.key:
        await _check_log_key_free(db, log_type.category_id, changes["key"], exclude_id=log_type.id)
    for name, value in changes.items():
        setattr(log_type, name, value)
    await db.flush()
    return log_type


async def delete_log_type(db: AsyncSession, log_type_id: int) -> None:
    log_type = await get_log_type(db, log_type_id)
    log_type.deleted_at = datetime.now(UTC)
    await db.flush()


async def effective_log_types(db: AsyncSession, category_id: int) -> list[LogEntryType]:
    chain = await ancestors(db, category_id)
    depth = {c.id: i for i, c in enumerate(chain)}
    rows = await db.scalars(
        select(LogEntryType).where(
            LogEntryType.category_id.in_(depth), LogEntryType.deleted_at.is_(None)
        )
    )
    return sorted(rows, key=lambda t: (depth[t.category_id], t.id))
