"""Test data helpers shared by all server tests."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def make_category(
    db: AsyncSession,
    name: str = "Cat",
    parent: Any = None,
    tracking_mode: str | None = None,
    fields: list[dict] | None = None,
    **kw: Any,
):
    from pick2light.core.categories import CategoryIn, FieldDefIn, create_category

    data = CategoryIn(
        name=name,
        parent_id=parent.id if parent is not None else None,
        tracking_mode=tracking_mode,
        fields=[FieldDefIn(**f) for f in (fields or [])],
        **kw,
    )
    return await create_category(db, data)


async def make_location(db: AsyncSession, name: str = "Loc", parent: Any = None, **kw: Any):
    from pick2light.core.locations import LocationIn, create_location

    return await create_location(
        db, LocationIn(name=name, parent_id=parent.id if parent is not None else None, **kw)
    )


async def make_item(db: AsyncSession, category: Any, name: str = "Item", **kw: Any):
    from pick2light.core.items import ItemIn, create_item

    return await create_item(db, ItemIn(category_id=category.id, name=name, **kw))


async def make_unit(db: AsyncSession, item: Any, **kw: Any):
    from pick2light.core.units import UnitIn, create_unit

    return await create_unit(db, UnitIn(item_id=item.id, **kw))


SCREW_FIELDS = [
    {"key": "thread", "type": "select", "options": [{"value": "M3"}, {"value": "M4"}]},
    {"key": "length", "type": "number", "number_unit": "mm"},
    {
        "key": "head",
        "type": "select",
        "options": [{"value": "socket_head", "label": "Socket head", "sku_code": "SHCS"}],
    },
]
RES_FIELDS = [
    {"key": "resistance", "type": "number", "number_unit": "Ω", "number_si_prefixes": True},
    {"key": "package", "type": "select", "options": [{"value": "0805"}, {"value": "0603"}]},
]
