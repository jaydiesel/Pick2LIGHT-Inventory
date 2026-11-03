"""Starter category packs: bundled JSON templates that seed categories, fields and log types.

Services flush but never commit; the request-scoped session commits.
"""

import json
import re
from importlib import resources

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core import categories as svc
from pick2light.core.categories import (
    CategoryIn,
    FieldBase,
    FieldDefIn,
    LogEntryTypeIn,
    TrackingMode,
)
from pick2light.errors import NotFound, ValidationFailed
from pick2light.models import Category, FieldDefinition, LocationType, LogEntryType

# --------------------------------------------------------------------------- schemas


class PackLocationType(BaseModel):
    name: str
    icon: str | None = None


class CategoryNode(BaseModel):
    name: str
    icon: str | None = None
    tracking_mode: TrackingMode | None = None
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
    location_types: list[PackLocationType] = []
    categories: list[CategoryNode] = []


class PackSummary(BaseModel):
    id: str
    name: str
    description: str
    category_count: int


class PackResult(BaseModel):
    created: int = 0
    skipped: int = 0


# --------------------------------------------------------------------------- built-in packs


def _pack_dir() -> resources.abc.Traversable:
    return resources.files("pick2light") / "packs"


def _count(nodes: list[CategoryNode]) -> int:
    return sum(1 + _count(n.children) for n in nodes)


def list_builtin_packs() -> list[PackSummary]:
    summaries = []
    for entry in sorted(_pack_dir().iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            pack = Pack.model_validate_json(entry.read_text(encoding="utf-8"))
            summaries.append(
                PackSummary(
                    id=pack.id,
                    name=pack.name,
                    description=pack.description,
                    category_count=_count(pack.categories),
                )
            )
    return summaries


def load_builtin_pack(pack_id: str) -> Pack:
    if not re.fullmatch(r"[a-z0-9_-]+", pack_id):
        raise NotFound(f"Pack '{pack_id}' not found")
    entry = _pack_dir() / f"{pack_id}.json"
    if not entry.is_file():
        raise NotFound(f"Pack '{pack_id}' not found")
    return Pack.model_validate_json(entry.read_text(encoding="utf-8"))


def parse_pack(raw: bytes | str) -> Pack:
    """Parse an uploaded pack document; malformed input is a validation error."""
    try:
        return Pack.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailed({"file": "not a valid pack file"}, "Invalid pack file") from exc


# --------------------------------------------------------------------------- apply


async def _find_child(db: AsyncSession, parent_id: int | None, name: str) -> Category | None:
    return await db.scalar(
        select(Category)
        .where(
            Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
            Category.name == name,
            Category.deleted_at.is_(None),
        )
        .limit(1)
    )


async def _related(db: AsyncSession, category_id: int) -> list[int]:
    """The category's ancestors and descendants (and itself): where keys must stay unique."""
    ids = [c.id for c in await svc.ancestors(db, category_id)]
    return ids + await svc.descendant_ids(db, category_id)


async def _apply_node(
    db: AsyncSession, node: CategoryNode, parent_id: int | None, result: PackResult
) -> None:
    category = await _find_child(db, parent_id, node.name)
    if category is None:
        category = await svc.create_category(
            db,
            CategoryIn(
                name=node.name,
                parent_id=parent_id,
                icon=node.icon,
                tracking_mode=node.tracking_mode,
                sku_prefix=node.sku_prefix,
                sku_pattern=node.sku_pattern,
                unit_id_pattern=node.unit_id_pattern,
            ),
        )
        result.created += 1
    else:
        result.skipped += 1

    if node.fields:
        related = await _related(db, category.id)
        taken = set(
            await db.scalars(
                select(FieldDefinition.key).where(FieldDefinition.category_id.in_(related))
            )
        )
        for field in node.fields:
            if field.key not in taken:
                await svc.add_field(db, category.id, field)
                taken.add(field.key)
    if node.log_types:
        related = await _related(db, category.id)
        taken = set(
            await db.scalars(
                select(LogEntryType.key).where(
                    LogEntryType.category_id.in_(related), LogEntryType.deleted_at.is_(None)
                )
            )
        )
        for log_type in node.log_types:
            if log_type.key not in taken:
                await svc.create_log_type(db, category.id, log_type)
                taken.add(log_type.key)

    for child in node.children:
        await _apply_node(db, child, category.id, result)


async def apply_pack(db: AsyncSession, pack: Pack, parent_id: int | None = None) -> PackResult:
    """Create the pack's categories under `parent_id`; anything that already exists is skipped.

    A category with the same name under the same parent is not recreated (its children are
    still processed); fields and log types whose key already exists are left alone.
    """
    if parent_id is not None:
        await svc.get_category(db, parent_id)
    existing = set(await db.scalars(select(LocationType.name)))
    for location_type in pack.location_types:
        if location_type.name not in existing:
            db.add(LocationType(name=location_type.name, icon=location_type.icon))
            existing.add(location_type.name)
    result = PackResult()
    for node in pack.categories:
        await _apply_node(db, node, parent_id, result)
    await db.flush()
    return result


# --------------------------------------------------------------------------- export


def _log_type_in(t: LogEntryType) -> LogEntryTypeIn:
    return LogEntryTypeIn(
        key=t.key,
        name=t.name,
        icon=t.icon,
        applies_to=t.applies_to,
        fields=[FieldBase.model_validate(f) for f in t.fields],
        summary_fields=list(t.summary_fields),
    )


async def _export_node(db: AsyncSession, category: Category, root: bool = False) -> CategoryNode:
    """`root` nodes also carry what they inherit, so the subtree can be applied on its own."""
    own = [category.id] if not root else [c.id for c in await svc.ancestors(db, category.id)]
    depth = {cid: i for i, cid in enumerate(own)}
    fields = sorted(
        await db.scalars(select(FieldDefinition).where(FieldDefinition.category_id.in_(own))),
        key=lambda f: (depth[f.category_id], f.order, f.id),
    )
    log_types = sorted(
        await db.scalars(
            select(LogEntryType).where(
                LogEntryType.category_id.in_(own), LogEntryType.deleted_at.is_(None)
            )
        ),
        key=lambda t: (depth[t.category_id], t.id),
    )
    mode = await svc.effective_tracking_mode(db, category.id) if root else category.tracking_mode
    children = await db.scalars(
        select(Category)
        .where(Category.parent_id == category.id, Category.deleted_at.is_(None))
        .order_by(Category.name, Category.id)
    )
    return CategoryNode(
        name=category.name,
        icon=category.icon,
        tracking_mode=mode,
        sku_prefix=category.sku_prefix,
        sku_pattern=category.sku_pattern,
        unit_id_pattern=category.unit_id_pattern,
        fields=[FieldDefIn.model_validate(f, from_attributes=True) for f in fields],
        log_types=[_log_type_in(t) for t in log_types],
        children=[await _export_node(db, c) for c in children],
    )


async def export_pack(db: AsyncSession, category_id: int) -> Pack:
    """The category's subtree as a pack (own fields and log types only, no location types)."""
    category = await svc.get_category(db, category_id)
    slug = re.sub(r"[^a-z0-9]+", "-", category.name.lower()).strip("-") or "category"
    return Pack(
        id=slug,
        name=category.name,
        description=category.description or "",
        categories=[await _export_node(db, category, root=True)],
    )
