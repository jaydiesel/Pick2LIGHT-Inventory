from fastapi import APIRouter, Depends

from pick2light.api import (
    attachments,
    auth,
    barcodes,
    categories,
    health,
    io,
    items,
    location_types,
    locations,
    logs,
    purchase,
    scan,
    search,
    settings,
    setup,
    stock,
    trash,
    units,
)
from pick2light.api.deps import require_auth

PUBLIC = [health.router, auth.router, settings.public_router, setup.public_router]
PROTECTED = [
    settings.router,
    categories.router,
    location_types.router,
    locations.router,
    barcodes.router,
    items.router,
    units.router,
    stock.router,
    logs.router,
    attachments.router,
    purchase.router,
    search.router,
    trash.router,
    setup.router,
    scan.router,
    io.router,
]

api_router = APIRouter()
for public in PUBLIC:
    api_router.include_router(public)
protected = APIRouter(dependencies=[Depends(require_auth)])
for router in PROTECTED:
    protected.include_router(router)
api_router.include_router(protected)
