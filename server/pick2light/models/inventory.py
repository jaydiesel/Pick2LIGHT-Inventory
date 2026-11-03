from sqlalchemy import BigInteger, CheckConstraint, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin


class Barcode(TimestampMixin, Base):
    __tablename__ = "barcode"
    __table_args__ = (
        CheckConstraint("target_type IN ('item','unit','location')", name="target_type"),
        CheckConstraint(
            "kind IN ('sku','unit_code','location_code','manufacturer','supplier','custom')", name="kind"
        ),
        Index("ix_barcode_target", "target_type", "target_id"),
        Index("ix_barcode_code_lower", text("lower(code)")),
    )

    code: Mapped[str] = mapped_column(String(512), unique=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
