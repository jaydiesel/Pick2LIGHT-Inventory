"""Where an item was bought, for the Reorder list (spec §3.2 `purchase_source`)."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.items import get_item
from pick2light.errors import NotFound, ValidationFailed
from pick2light.models import PurchaseSource


class _Fields(BaseModel):
    url: str | None = None
    supplier_part_number: str | None = Field(default=None, max_length=120)
    manufacturer_part_number: str | None = Field(default=None, max_length=120)
    unit_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    pack_quantity: float | None = Field(default=None, gt=0)
    last_ordered_at: date | None = None
    order_reference: str | None = Field(default=None, max_length=120)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class PurchaseSourceIn(_Fields):
    supplier: str = Field(min_length=1, max_length=120)


class PurchaseSourcePatch(_Fields):
    supplier: str | None = Field(default=None, min_length=1, max_length=120)


class PurchaseSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    supplier: str
    url: str | None
    supplier_part_number: str | None
    manufacturer_part_number: str | None
    unit_price: float | None
    currency: str | None
    pack_quantity: float | None
    last_ordered_at: date | None
    order_reference: str | None


def _check_url(url: str | None) -> None:
    if url and not url.strip().startswith(("http://", "https://")):
        raise ValidationFailed({"url": "Must start with http:// or https://"})


async def get_source(db: AsyncSession, source_id: int) -> PurchaseSource:
    s = await db.get(PurchaseSource, source_id)
    if s is None:
        raise NotFound(f"Purchase source {source_id} not found")
    return s


async def create_source(db: AsyncSession, item_id: int, data: PurchaseSourceIn) -> PurchaseSource:
    await get_item(db, item_id)
    _check_url(data.url)
    s = PurchaseSource(item_id=item_id, **data.model_dump())
    db.add(s)
    await db.flush()
    return s


async def update_source(db: AsyncSession, source_id: int, data: PurchaseSourcePatch) -> PurchaseSource:
    s = await get_source(db, source_id)
    if "url" in data.model_fields_set:
        _check_url(data.url)
    for attr in data.model_fields_set:
        value = getattr(data, attr)
        if attr == "supplier" and value is None:
            continue
        setattr(s, attr, value)
    await db.flush()
    return s


async def delete_source(db: AsyncSession, source_id: int) -> None:
    await db.delete(await get_source(db, source_id))
    await db.flush()


async def list_sources(db: AsyncSession, item_id: int) -> list[PurchaseSource]:
    return list(
        await db.scalars(
            select(PurchaseSource).where(PurchaseSource.item_id == item_id).order_by(PurchaseSource.id)
        )
    )
