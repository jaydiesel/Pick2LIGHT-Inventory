"""Where an item was bought: suppliers, part numbers, prices.

Services flush but never commit; the request-scoped session commits.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.items import get_item
from pick2light.core.urls import is_http_url
from pick2light.errors import NotFound
from pick2light.models import PurchaseSource

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Supplier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Currency = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$")
]


def _check_url(value: str | None) -> str | None:
    if value is not None and not is_http_url(value.strip()):
        raise ValueError("Must be an http:// or https:// URL")
    return value.strip() if value is not None else None


class PurchaseSourceIn(BaseModel):
    supplier: Supplier
    url: str | None = None
    supplier_part_number: Text200 | None = None
    manufacturer_part_number: Text200 | None = None
    unit_price: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4)] | None = None
    currency: Currency | None = None
    pack_quantity: Annotated[int, Field(ge=1)] | None = None
    last_ordered_at: date | None = None
    order_reference: Text200 | None = None

    _url = field_validator("url")(_check_url)


class PurchaseSourcePatch(PurchaseSourceIn):
    """Every field optional; only the ones sent change. `supplier` cannot be cleared."""

    supplier: Supplier | None = None  # type: ignore[assignment]

    @field_validator("supplier")
    @classmethod
    def _supplier_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("required")
        return value


class PurchaseSourceOut(BaseModel):
    id: int
    item_id: int
    supplier: str
    url: str | None
    supplier_part_number: str | None
    manufacturer_part_number: str | None
    unit_price: float | None
    currency: str | None
    pack_quantity: int | None
    last_ordered_at: date | None
    order_reference: str | None
    created_at: datetime
    updated_at: datetime


def source_out(source: PurchaseSource) -> PurchaseSourceOut:
    return PurchaseSourceOut.model_validate(source, from_attributes=True)


async def get_source(db: AsyncSession, source_id: int) -> PurchaseSource:
    source = await db.get(PurchaseSource, source_id)
    if source is None:
        raise NotFound(f"Purchase source {source_id} not found")
    return source


async def create_source(db: AsyncSession, item_id: int, data: PurchaseSourceIn) -> PurchaseSource:
    await get_item(db, item_id)
    source = PurchaseSource(item_id=item_id, **data.model_dump())
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return source


async def update_source(
    db: AsyncSession, source_id: int, patch: PurchaseSourcePatch
) -> PurchaseSource:
    source = await get_source(db, source_id)
    for key, value in patch.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    await db.flush()
    await db.refresh(source)
    return source


async def delete_source(db: AsyncSession, source_id: int) -> None:
    await db.delete(await get_source(db, source_id))
    await db.flush()


async def list_sources(db: AsyncSession, item_id: int) -> list[PurchaseSource]:
    await get_item(db, item_id)
    result = await db.scalars(
        select(PurchaseSource).where(PurchaseSource.item_id == item_id).order_by(PurchaseSource.id)
    )
    return list(result)
