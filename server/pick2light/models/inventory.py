from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, SoftDeleteMixin, TimestampMixin

BARCODE_TARGET_TYPES = ("item", "unit", "location")
UNIT_CONDITIONS = ("new", "tested_good", "untested", "faulty", "for_parts")
UNIT_STATUSES = ("in_stock", "checked_out", "consumed", "disposed")
MOVEMENT_REASONS = (
    "create",
    "import",
    "check_out",
    "check_in",
    "consume",
    "move",
    "adjust",
    "stocktake",
    "undo",
)
MOVEMENT_SOURCES = ("ui", "scan", "import", "api", "stocktake")
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
    default_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL")
    )
    photo_attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachment.id", ondelete="SET NULL")
    )
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
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL"), index=True
    )
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


class Stock(TimestampMixin, Base):
    """Bulk quantity of an item in one location. Rows that reach 0 are kept as history."""

    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id"),
        CheckConstraint("quantity >= 0", name="quantity"),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("location.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal(0), server_default="0"
    )


class StockMovement(TimestampMixin, Base):
    """Append-only audit trail of every quantity and unit status change."""

    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('create', 'import', 'check_out', 'check_in', 'consume', 'move',"
            " 'adjust', 'stocktake', 'undo')",
            name="reason",
        ),
        CheckConstraint("source IN ('ui', 'scan', 'import', 'api', 'stocktake')", name="source"),
    )

    # History survives the purge of what it refers to: these become NULL (migration 0008).
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("item.id", ondelete="SET NULL"), index=True
    )
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("unit.id", ondelete="SET NULL"), index=True
    )
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL")
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL")
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reason: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), default="ui", server_default="ui")
    reverses_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movement.id"), unique=True
    )
    note: Mapped[str | None] = mapped_column(Text)


class LogEntry(TimestampMixin, Base):
    """One history record (e.g. a capacity test) on a unit or on an item.

    Exactly one of `unit_id` / `item_id` is set. The newest entry per log type is exposed
    by the `unit_latest_values` / `item_latest_values` views (see migration 0006).
    """

    __tablename__ = "log_entry"
    __table_args__ = (CheckConstraint("(unit_id IS NULL) <> (item_id IS NULL)", name="one_target"),)

    log_entry_type_id: Mapped[int] = mapped_column(ForeignKey("log_entry_type.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)


Index("ix_log_entry_unit", LogEntry.unit_id, LogEntry.log_entry_type_id, LogEntry.performed_at)
Index("ix_log_entry_item", LogEntry.item_id, LogEntry.log_entry_type_id, LogEntry.performed_at)
