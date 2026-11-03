from fastapi import APIRouter

from pick2light.api import barcodes, categories, health, items, location_types, locations, stock, units

api_router = APIRouter()
for module in (health, categories, location_types, locations, barcodes, items, units, stock):
    api_router.include_router(module.router)
