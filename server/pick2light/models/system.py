from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pick2light.models.base import Base, TimestampMixin


class Setting(TimestampMixin, Base):
    """One stored setting; settings that were never changed have no row (see DEFAULTS)."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[Any] = mapped_column(JSONB)


class AppUser(TimestampMixin, Base):
    """The single account of the installation."""

    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
