from fastapi import APIRouter

from pick2light.api import barcodes, categories, health, items, location_types, locations, units

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(categories.router)
api_router.include_router(location_types.router)
api_router.include_router(locations.router)
api_router.include_router(barcodes.router)
api_router.include_router(items.router)
api_router.include_router(units.router)
