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
    search,
    stock,
    trash,
    units,
)

ROUTERS = [
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
    search,
    trash,
]

api_router = APIRouter()
for module in ROUTERS:
    api_router.include_router(module.router)
