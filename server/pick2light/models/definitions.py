from typing import Any

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
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, SoftDeleteMixin, TimestampMixin

FIELD_TYPES = (
    "text",
    "long_text",
    "number",
    "select",
    "multi_select",
    "boolean",
    "date",
    "url",
    "file",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Category(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "category"
    __table_args__ = (
        CheckConstraint(
            "tracking_mode IS NULL OR tracking_mode IN ('bulk', 'unit')", name="tracking_mode"
        ),
    )

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    # NULL = inherit from the parent category (root default: bulk).
    tracking_mode: Mapped[str | None] = mapped_column(String(10))
    sku_prefix: Mapped[str | None] = mapped_column(String(50))
    sku_pattern: Mapped[str | None] = mapped_column(String(200))
    unit_id_pattern: Mapped[str | None] = mapped_column(String(200))
    # Label templates arrive later; these become foreign keys then.
    default_label_template_id: Mapped[int | None] = mapped_column(BigInteger)
    default_unit_label_template_id: Mapped[int | None] = mapped_column(BigInteger)


class FieldDefinition(TimestampMixin, Base):
    __tablename__ = "field_definition"
    __table_args__ = (
        UniqueConstraint("category_id", "key"),
        CheckConstraint(_in_list("type", FIELD_TYPES), name="type"),
        CheckConstraint("scope IN ('item', 'unit')", name="scope"),
    )

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    key: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(200))
    help_text: Mapped[str | None] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    type: Mapped[str] = mapped_column(String(20))
    scope: Mapped[str] = mapped_column(String(10), default="item", server_default="item")
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    filterable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    show_on_label: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    number_unit: Mapped[str | None] = mapped_column(String(20))
    number_si_prefixes: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    min: Mapped[float | None] = mapped_column(Float)
    max: Mapped[float | None] = mapped_column(Float)
    decimals: Mapped[int | None] = mapped_column(Integer)
    options: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class LogEntryType(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "log_entry_type"
    __table_args__ = (CheckConstraint("applies_to IN ('unit', 'item')", name="applies_to"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    key: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(100))
    applies_to: Mapped[str] = mapped_column(String(10))
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    summary_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class LocationType(TimestampMixin, Base):
    __tablename__ = "location_type"

    name: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(100))


class CategorySequence(Base):
    """Per-category counters for SKU and unit-code generation (`kind` = "sku" | "unit")."""

    __tablename__ = "category_sequence"
    __table_args__ = (CheckConstraint("kind IN ('sku', 'unit')", name="kind"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
