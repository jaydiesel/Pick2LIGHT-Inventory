from fastapi import APIRouter

from pick2light.api import (
    attachments,
    barcodes,
    categories,
    health,
    items,
    location_types,
    locations,
    logs,
    purchase,
    stock,
    units,
)

api_router = APIRouter()
for module in (
    health,
    categories,
    location_types,
    locations,
    barcodes,
    items,
    units,
    stock,
    logs,
    attachments,
    purchase,
):
    api_router.include_router(module.router)
