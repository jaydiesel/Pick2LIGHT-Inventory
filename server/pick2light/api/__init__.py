from fastapi import APIRouter

from pick2light.api import health

api_router = APIRouter()
api_router.include_router(health.router)
