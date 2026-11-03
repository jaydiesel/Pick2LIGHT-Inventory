"""Test data builders. Later tasks extend this module."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.categories import CategoryIn, FieldDefIn, add_field, create_category
from pick2light.core.locations import LocationIn, create_location
from pick2light.models import Category, Location


async def make_category(
    db: AsyncSession,
    name: str = "Cat",
    parent: Category | None = None,
    tracking_mode: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    **kw: Any,
) -> Category:
    category = await create_category(
        db,
        CategoryIn.model_validate(
            {
                "name": name,
                "parent_id": parent.id if parent else None,
                "tracking_mode": tracking_mode,
                **kw,
            }
        ),
    )
    for spec in fields or []:
        await add_field(db, category.id, FieldDefIn.model_validate({"label": spec["key"], **spec}))
    return category


async def make_location(
    db: AsyncSession, name: str = "Loc", parent: Location | None = None, **kw: Any
) -> Location:
    return await create_location(
        db,
        LocationIn.model_validate({"name": name, "parent_id": parent.id if parent else None, **kw}),
    )
