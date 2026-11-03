from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin

ATTACHMENT_OWNER_TYPES = ("item", "unit", "location", "log_entry", "category")
ATTACHMENT_KINDS = ("photo", "datasheet", "document", "other")


class Attachment(TimestampMixin, Base):
    """A file stored under the attachments directory, or a link to an external document.

    Exactly one of `storage_path` (relative to the attachments directory) and `url` is set.
    The owner is polymorphic, so `owner_id` has no foreign key.
    """

    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('item', 'unit', 'location', 'log_entry', 'category')",
            name="owner_type",
        ),
        CheckConstraint("kind IN ('photo', 'datasheet', 'document', 'other')", name="kind"),
        CheckConstraint("(storage_path IS NULL) <> (url IS NULL)", name="file_or_url"),
        Index("ix_attachment_owner", "owner_type", "owner_id"),
    )

    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_path: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)


class PurchaseSource(TimestampMixin, Base):
    __tablename__ = "purchase_source"

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    supplier: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    supplier_part_number: Mapped[str | None] = mapped_column(String(200))
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(200))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    pack_quantity: Mapped[int | None] = mapped_column()
    last_ordered_at: Mapped[date | None] = mapped_column(Date)
    order_reference: Mapped[str | None] = mapped_column(String(200))
