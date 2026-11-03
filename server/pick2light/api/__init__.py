from fastapi import APIRouter

from pick2light.api import barcodes, categories, health, location_types, locations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(categories.router)
api_router.include_router(location_types.router)
api_router.include_router(locations.router)
api_router.include_router(barcodes.router)
