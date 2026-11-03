from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, SoftDeleteMixin, TimestampMixin

BARCODE_TARGET_TYPES = ("item", "unit", "location")
UNIT_CONDITIONS = ("new", "tested_good", "untested", "faulty", "for_parts")
UNIT_STATUSES = ("in_stock", "checked_out", "consumed", "disposed")
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


class Item(TimestampMixin, SoftDeleteMixin, Base):
    """A product / SKU. `sku` stays unique across soft-deleted rows so a restore cannot collide."""

    __tablename__ = "item"

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    sku: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    min_stock: Mapped[int | None] = mapped_column(Integer)
    default_location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"))
    # The foreign key to `attachment` is added with attachments (Task 10).
    photo_attachment_id: Mapped[int | None] = mapped_column(BigInteger)
    # Name, SKU, description and the searchable text of `attrs`, NFKC-normalised;
    # rebuilt by `refresh_search_text`. `search_vector` is derived from it by Postgres.
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', search_text)", persisted=True),
        deferred=True,
    )


Index("ix_item_search_vector", Item.search_vector, postgresql_using="gin")
Index(
    "ix_item_attrs", Item.attrs, postgresql_using="gin", postgresql_ops={"attrs": "jsonb_path_ops"}
)
Index(
    "ix_item_name_trgm", Item.name, postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
)
Index("ix_item_sku_trgm", Item.sku, postgresql_using="gin", postgresql_ops={"sku": "gin_trgm_ops"})


class Unit(TimestampMixin, SoftDeleteMixin, Base):
    """One individually tracked physical thing.

    `location_id` is kept while checked out (check-in returns it home) and cleared once
    consumed or disposed. `unit_code` stays unique across soft-deleted rows.
    """

    __tablename__ = "unit"
    __table_args__ = (
        CheckConstraint(
            "condition IN ('new', 'tested_good', 'untested', 'faulty', 'for_parts')",
            name="condition",
        ),
        CheckConstraint(
            "status IN ('in_stock', 'checked_out', 'consumed', 'disposed')", name="status"
        ),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    unit_code: Mapped[str] = mapped_column(String(200), unique=True)
    serial_number: Mapped[str | None] = mapped_column(String(200))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"), index=True)
    condition: Mapped[str] = mapped_column(
        String(20), default="untested", server_default="untested"
    )
    status: Mapped[str] = mapped_column(String(20), default="in_stock", server_default="in_stock")
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


Index(
    "ix_unit_attrs", Unit.attrs, postgresql_using="gin", postgresql_ops={"attrs": "jsonb_path_ops"}
)
