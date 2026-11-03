from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, SoftDeleteMixin, TimestampMixin


class Location(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "location"
    __table_args__ = (CheckConstraint("light_children IN ('inherit','on','off')", name="light_children"),)

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"), index=True)
    location_type_id: Mapped[int | None] = mapped_column(ForeignKey("location_type.id"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    photo_attachment_id: Mapped[int | None] = mapped_column(ForeignKey("attachment.id", ondelete="SET NULL"))
    light_children: Mapped[str] = mapped_column(String(8), default="inherit")
    grid_row: Mapped[int | None] = mapped_column(Integer)
    grid_col: Mapped[int | None] = mapped_column(Integer)
