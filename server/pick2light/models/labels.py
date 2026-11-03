from sqlalchemy import CheckConstraint, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin


class LabelTemplate(TimestampMixin, Base):
    __tablename__ = "label_template"
    __table_args__ = (CheckConstraint("target IN ('item','unit','location','command')", name="target"),)

    name: Mapped[str] = mapped_column(String(100), unique=True)
    width_mm: Mapped[float] = mapped_column(Float)
    height_mm: Mapped[float] = mapped_column(Float)
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    target: Mapped[str] = mapped_column(String(16))
    layout: Mapped[list] = mapped_column(JSONB, default=list)
