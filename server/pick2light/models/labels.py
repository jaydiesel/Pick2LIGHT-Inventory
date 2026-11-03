from typing import Any

from sqlalchemy import CheckConstraint, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin

LABEL_TARGETS = ("item", "unit", "location", "command")


class LabelTemplate(TimestampMixin, Base):
    """A label layout: a list of elements positioned in millimetres (see `pick2light.labels`)."""

    __tablename__ = "label_template"
    __table_args__ = (
        CheckConstraint("target IN ('item', 'unit', 'location', 'command')", name="target"),
        CheckConstraint("width_mm > 0 AND height_mm > 0", name="size"),
        CheckConstraint("dpi > 0", name="dpi"),
    )

    name: Mapped[str] = mapped_column(String(200))
    width_mm: Mapped[float] = mapped_column(Float)
    height_mm: Mapped[float] = mapped_column(Float)
    dpi: Mapped[int] = mapped_column(Integer, default=203, server_default="203")
    target: Mapped[str] = mapped_column(String(10))
    layout: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
