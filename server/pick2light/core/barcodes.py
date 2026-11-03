"""The barcode registry: one table behind every scan lookup."""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import Conflict, ValidationFailed
from pick2light.models import Barcode

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


async def lookup_barcode(db: AsyncSession, code: str) -> Barcode | None:
    """Exact (case-sensitive) match, else the single case-insensitive match, else None."""
    code = code.strip()
    exact = await db.scalar(select(Barcode).where(Barcode.code == code))
    if exact is not None:
        return exact
    matches = (
        await db.scalars(select(Barcode).where(func.lower(Barcode.code) == code.lower()).limit(2))
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
