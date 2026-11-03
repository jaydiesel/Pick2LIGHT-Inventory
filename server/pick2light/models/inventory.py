from sqlalchemy import BigInteger, CheckConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin

BARCODE_TARGET_TYPES = ("item", "unit", "location")
BARCODE_KINDS = ("sku", "unit_code", "location_code", "manufacturer", "supplier", "custom")


class Barcode(TimestampMixin, Base):
    """Every scannable code (SKUs, unit codes, location codes, manufacturer barcodes)."""

    __tablename__ = "barcode"
    __table_args__ = (
        CheckConstraint("target_type IN ('item', 'unit', 'location')", name="target_type"),
        CheckConstraint(
            "kind IN ('sku', 'unit_code', 'location_code', 'manufacturer', 'supplier', 'custom')",
            name="kind",
        ),
    )

    code: Mapped[str] = mapped_column(String(500), unique=True)
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))


# Case-insensitive fallback lookup (lookup_barcode) and "all barcodes of this target".
Index("ix_barcode_lower_code", func.lower(Barcode.code))
Index("ix_barcode_target", Barcode.target_type, Barcode.target_id)
