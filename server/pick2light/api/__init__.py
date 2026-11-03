from fastapi import APIRouter

from pick2light.api import barcodes, categories, health, location_types, locations

api_router = APIRouter()
for module in (health, categories, location_types, locations, barcodes):
    api_router.include_router(module.router)
