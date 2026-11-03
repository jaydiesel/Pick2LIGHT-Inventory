"""Starter category packs: JSON files that create categories, fields and log types (spec §10.2, §14)."""

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as cats
from pick2light.core.categories import FieldDefIn, LocationTypeIn, LogEntryTypeIn
from pick2light.errors import Conflict, NotFound
from pick2light.models import Category, FieldDefinition, LocationType, LogEntryType

PACK_DIR = Path(__file__).resolve().parent.parent / "packs"
DEFAULT_LOCATION_TYPES = ["Room", "Cabinet", "Drawer", "Shelf", "Bin", "Tote", "Box"]


class CategoryNode(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = None
    description: str | None = None
    tracking_mode: cats.TrackingMode | None = None
    sku_prefix: str | None = None
    sku_pattern: str | None = None
    unit_id_pattern: str | None = None
    fields: list[FieldDefIn] = []
    log_types: list[LogEntryTypeIn] = []
    children: list["CategoryNode"] = []


class Pack(BaseModel):
    id: str
    name: str
    description: str = ""
    location_types: list[LocationTypeIn] = []
    categories: list[CategoryNode] = []


class PackSummary(BaseModel):
    id: str
    name: str
    description: str
    category_count: int


class PackResult(BaseModel):
    created: int = 0
    skipped: int = 0


def _count(nodes: list[CategoryNode]) -> int:
    return sum(1 + _count(n.children) for n in nodes)


def list_builtin_packs() -> list[PackSummary]:
    order = ["electronics", "hardware", "batteries", "computer", "generic"]
    packs = [load_builtin_pack(p.stem) for p in PACK_DIR.glob("*.json")]
    packs.sort(key=lambda p: order.index(p.id) if p.id in order else len(order))
    return [
        PackSummary(id=p.id, name=p.name, description=p.description, category_count=_count(p.categories))
        for p in packs
    ]


def load_builtin_pack(pack_id: str) -> Pack:
    path = PACK_DIR / f"{pack_id}.json"
    if not re.fullmatch(r"[a-z0-9_-]+", pack_id) or not path.exists():
        raise NotFound(f"No starter pack called '{pack_id}'")
    return Pack.model_validate(json.loads(path.read_text(encoding="utf-8")))


async def seed_location_types(db: AsyncSession, names: list[str] | None = None) -> None:
    for name in names or DEFAULT_LOCATION_TYPES:
        exists = await db.scalar(select(LocationType.id).where(func.lower(LocationType.name) == name.lower()))
        if exists is None:
            await cats.create_location_type(db, LocationTypeIn(name=name))


async def _apply_node(
    db: AsyncSession, node: CategoryNode, parent_id: int | None, result: PackResult
) -> None:
    parent_clause = Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    existing = await db.scalar(
        select(Category).where(
            parent_clause, func.lower(Category.name) == node.name.lower(), Category.deleted_at.is_(None)
        )
    )
    if existing is not None:
        result.skipped += 1
        cat = existing
    else:
        cat = await cats.create_category(
            db,
            cats.CategoryIn(
                name=node.name,
                parent_id=parent_id,
                icon=node.icon,
                description=node.description,
                tracking_mode=node.tracking_mode,
                sku_prefix=node.sku_prefix,
                sku_pattern=node.sku_pattern,
                unit_id_pattern=node.unit_id_pattern,
            ),
        )
        result.created += 1
    for field in node.fields:
        try:
            await cats.add_field(db, cat.id, field)
        except Conflict:
            pass  # key already defined in this category family
    for log_type in node.log_types:
        try:
            await cats.create_log_type(db, cat.id, log_type)
        except Conflict:
            pass
    for child in node.children:
        await _apply_node(db, child, cat.id, result)


async def apply_pack(db: AsyncSession, pack: Pack, parent_id: int | None = None) -> PackResult:
    if parent_id is not None:
        await cats.get_category(db, parent_id)
    if pack.location_types:
        await seed_location_types(db, [lt.name for lt in pack.location_types])
    result = PackResult()
    for node in pack.categories:
        await _apply_node(db, node, parent_id, result)
    return result


async def _export_node(db: AsyncSession, cat: Category) -> CategoryNode:
    own_fields = await db.scalars(
        select(FieldDefinition)
        .where(FieldDefinition.category_id == cat.id)
        .order_by(FieldDefinition.order, FieldDefinition.id)
    )
    own_types = await db.scalars(
        select(LogEntryType).where(LogEntryType.category_id == cat.id, LogEntryType.deleted_at.is_(None))
    )
    children = await db.scalars(
        select(Category)
        .where(Category.parent_id == cat.id, Category.deleted_at.is_(None))
        .order_by(Category.name)
    )
    return CategoryNode(
        name=cat.name,
        icon=cat.icon,
        description=cat.description,
        tracking_mode=cat.tracking_mode,  # type: ignore[arg-type]
        sku_prefix=cat.sku_prefix,
        sku_pattern=cat.sku_pattern,
        unit_id_pattern=cat.unit_id_pattern,
        fields=[
            FieldDefIn(
                key=f.key,
                label=f.label,
                type=f.type,  # type: ignore[arg-type]
                scope=f.scope,  # type: ignore[arg-type]
                required=f.required,
                filterable=f.filterable,
                show_on_label=f.show_on_label,
                number_unit=f.number_unit,
                number_si_prefixes=f.number_si_prefixes,
                min=f.min,
                max=f.max,
                decimals=f.decimals,
                options=f.options,  # type: ignore[arg-type]
                help_text=f.help_text,
            )
            for f in own_fields
        ],
        log_types=[
            LogEntryTypeIn(
                key=t.key,
                name=t.name,
                icon=t.icon,
                applies_to=t.applies_to,  # type: ignore[arg-type]
                fields=[FieldDefIn(**{k: v for k, v in d.items() if k != "order"}) for d in t.fields],
                summary_fields=list(t.summary_fields),
            )
            for t in own_types
        ],
        children=[await _export_node(db, c) for c in children],
    )


async def export_pack(db: AsyncSession, category_id: int) -> Pack:
    cat = await cats.get_category(db, category_id)
    slug = re.sub(r"[^a-z0-9]+", "-", cat.name.lower()).strip("-") or "pack"
    return Pack(
        id=slug,
        name=cat.name,
        description=f"Exported from {cat.name}",
        categories=[await _export_node(db, cat)],
    )
