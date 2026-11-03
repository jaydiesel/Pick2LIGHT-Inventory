from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, SoftDeleteMixin, TimestampMixin


class Category(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "category"
    __table_args__ = (CheckConstraint("tracking_mode IN ('bulk','unit')", name="tracking_mode"),)

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    tracking_mode: Mapped[str | None] = mapped_column(String(8))
    sku_prefix: Mapped[str | None] = mapped_column(String(20))
    sku_pattern: Mapped[str | None] = mapped_column(String(200))
    unit_id_pattern: Mapped[str | None] = mapped_column(String(200))
    default_label_template_id: Mapped[int | None] = mapped_column(BigInteger)
    default_unit_label_template_id: Mapped[int | None] = mapped_column(BigInteger)


class FieldDefinition(TimestampMixin, Base):
    __tablename__ = "field_definition"
    __table_args__ = (
        UniqueConstraint("category_id", "key", name="category_key"),
        CheckConstraint("scope IN ('item','unit')", name="scope"),
    )

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(200))
    help_text: Mapped[str | None] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(8), default="item")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    filterable: Mapped[bool] = mapped_column(Boolean, default=False)
    show_on_label: Mapped[bool] = mapped_column(Boolean, default=False)
    number_unit: Mapped[str | None] = mapped_column(String(16))
    number_si_prefixes: Mapped[bool] = mapped_column(Boolean, default=False)
    min: Mapped[float | None] = mapped_column(Float)
    max: Mapped[float | None] = mapped_column(Float)
    decimals: Mapped[int | None] = mapped_column(Integer)
    options: Mapped[list] = mapped_column(JSONB, default=list)


class LogEntryType(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "log_entry_type"
    __table_args__ = (CheckConstraint("applies_to IN ('item','unit')", name="applies_to"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(64))
    applies_to: Mapped[str] = mapped_column(String(8), default="unit")
    fields: Mapped[list] = mapped_column(JSONB, default=list)
    summary_fields: Mapped[list] = mapped_column(JSONB, default=list)


class LocationType(TimestampMixin, Base):
    __tablename__ = "location_type"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    icon: Mapped[str | None] = mapped_column(String(64))


class CategorySequence(Base):
    __tablename__ = "category_sequence"
    __table_args__ = (CheckConstraint("kind IN ('sku','unit')", name="kind"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)
