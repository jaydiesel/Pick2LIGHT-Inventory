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
api_router.include_router(health.router)
api_router.include_router(categories.router)
api_router.include_router(location_types.router)
api_router.include_router(locations.router)
api_router.include_router(barcodes.router)
api_router.include_router(items.router)
api_router.include_router(units.router)
api_router.include_router(stock.router)
api_router.include_router(logs.router)
api_router.include_router(attachments.router)
api_router.include_router(purchase.router)
