"""ORM models. Import every model module here so Alembic autogenerate sees them."""

from pick2light.models.base import Base
from pick2light.models.definitions import (
    Category,
    CategorySequence,
    FieldDefinition,
    LocationType,
    LogEntryType,
)
from pick2light.models.files import Attachment, PurchaseSource
from pick2light.models.inventory import Barcode, Item, LogEntry, Stock, StockMovement, Unit
from pick2light.models.labels import LabelTemplate
from pick2light.models.locations import Location
from pick2light.models.system import AppUser, Setting

__all__ = [
    "AppUser",
    "Attachment",
    "Barcode",
    "Base",
    "Category",
    "CategorySequence",
    "FieldDefinition",
    "Item",
    "LabelTemplate",
    "Location",
    "LocationType",
    "LogEntry",
    "LogEntryType",
    "PurchaseSource",
    "Setting",
    "Stock",
    "StockMovement",
    "Unit",
]
