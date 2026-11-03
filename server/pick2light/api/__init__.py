from fastapi import APIRouter

from pick2light.api import categories, health, location_types

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(categories.router)
api_router.include_router(location_types.router)
