"""The barcode registry: one table behind every scan lookup."""

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import Conflict, ValidationFailed
from pick2light.models import Barcode, Item, Location, Unit

# Kinds created and removed together with their owner; never edited through the barcode API.
AUTOMATIC_KINDS = ("sku", "unit_code", "location_code")


async def code_exists(db: AsyncSession, code: str) -> bool:
    return await db.scalar(select(Barcode.id).where(Barcode.code == code).limit(1)) is not None


async def register_barcode(
    db: AsyncSession, code: str, target_type: str, target_id: int, kind: str
) -> Barcode:
    """Register ``code`` for a target. Idempotent for the same target; Conflict otherwise."""
    code = code.strip()
    if not code:
        raise ValidationFailed({"code": "must not be empty"})
    existing = await db.scalar(select(Barcode).where(Barcode.code == code))
    if existing is not None:
        if (existing.target_type, existing.target_id) == (target_type, target_id):
            return existing
        raise Conflict(f"Code {code!r} is already in use")
    barcode = Barcode(code=code, target_type=target_type, target_id=target_id, kind=kind)
    db.add(barcode)
    await db.flush()
    return barcode


def _target_in_trash() -> ColumnElement[bool]:
    """True for a barcode whose item, unit or location is soft-deleted."""
    return or_(
        *(
            and_(
                Barcode.target_type == name,
                exists().where(model.id == Barcode.target_id, model.deleted_at.is_not(None)),
            )
            for name, model in (("item", Item), ("unit", Unit), ("location", Location))
        )
    )


async def lookup_barcode(db: AsyncSession, code: str) -> Barcode | None:
    """Exact (case-sensitive) match, else the single case-insensitive match, else None.

    Codes kept on a soft-deleted target (manufacturer, supplier, custom) are not found.
    """
    code = code.strip()
    live = ~_target_in_trash()
    exact = await db.scalar(select(Barcode).where(Barcode.code == code, live))
    if exact is not None:
        return exact
    matches = (
        await db.scalars(
            select(Barcode).where(func.lower(Barcode.code) == code.lower(), live).limit(2)
        )
    ).all()
    return matches[0] if len(matches) == 1 else None


async def remove_barcodes_for(
    db: AsyncSession, target_type: str, target_id: int, kind: str | None = None
) -> None:
    stmt = delete(Barcode).where(Barcode.target_type == target_type, Barcode.target_id == target_id)
    if kind is not None:
        stmt = stmt.where(Barcode.kind == kind)
    await db.execute(stmt)
    await db.flush()
