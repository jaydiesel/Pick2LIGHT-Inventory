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
