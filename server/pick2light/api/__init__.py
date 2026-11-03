from fastapi import APIRouter

from pick2light.api import barcodes, categories, health, items, location_types, locations, units

api_router = APIRouter()
for module in (health, categories, location_types, locations, barcodes, items, units):
    api_router.include_router(module.router)
