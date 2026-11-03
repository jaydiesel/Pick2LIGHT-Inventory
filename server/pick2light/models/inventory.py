from datetime import datetime

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


class Item(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "item"
    __table_args__ = (
        Index("ix_item_attrs", "attrs", postgresql_using="gin", postgresql_ops={"attrs": "jsonb_path_ops"}),
        Index("ix_item_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_item_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("ix_item_sku_trgm", "sku", postgresql_using="gin", postgresql_ops={"sku": "gin_trgm_ops"}),
    )

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    sku: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    min_stock: Mapped[int | None] = mapped_column(Integer)
    default_location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id", ondelete="SET NULL"))
    photo_attachment_id: Mapped[int | None] = mapped_column(ForeignKey("attachment.id", ondelete="SET NULL"))
    search_text: Mapped[str] = mapped_column(Text, default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, coalesce(search_text, ''))", persisted=True)
    )


class Unit(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "unit"
    __table_args__ = (
        CheckConstraint(
            "condition IN ('new','tested_good','untested','faulty','for_parts')", name="condition"
        ),
        CheckConstraint("status IN ('in_stock','checked_out','consumed','disposed')", name="status"),
        Index("ix_unit_attrs", "attrs", postgresql_using="gin", postgresql_ops={"attrs": "jsonb_path_ops"}),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    unit_code: Mapped[str] = mapped_column(String(120), unique=True)
    serial_number: Mapped[str | None] = mapped_column(String(200))
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL"), index=True
    )
    condition: Mapped[str] = mapped_column(String(16), default="untested")
    status: Mapped[str] = mapped_column(String(16), default="in_stock")
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)


class Stock(TimestampMixin, Base):
    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id", name="item_location"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4, asdecimal=False), default=0)


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('create','import','check_out','check_in','consume','move','adjust','stocktake','undo')",
            name="reason",
        ),
        CheckConstraint("source IN ('ui','scan','import','api','stocktake')", name="source"),
    )

    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id", ondelete="SET NULL"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id", ondelete="SET NULL"), index=True)
    from_location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id", ondelete="SET NULL"))
    to_location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id", ondelete="SET NULL"))
    quantity_delta: Mapped[float] = mapped_column(Numeric(14, 4, asdecimal=False))
    reason: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="ui")
    reverses_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movement.id"), unique=True)
    note: Mapped[str | None] = mapped_column(Text)


class LogEntry(TimestampMixin, Base):
    __tablename__ = "log_entry"
    __table_args__ = (CheckConstraint("(unit_id IS NULL) <> (item_id IS NULL)", name="one_target"),)

    log_entry_type_id: Mapped[int] = mapped_column(
        ForeignKey("log_entry_type.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    values: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
