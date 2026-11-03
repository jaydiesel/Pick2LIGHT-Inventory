from fastapi import APIRouter

from pick2light.api import (
    attachments,
    auth,
    barcodes,
    categories,
    health,
    items,
    location_types,
    locations,
    logs,
    packs,
    purchase,
    scan,
    search,
    settings,
    setup,
    stock,
    trash,
    units,
)
from pick2light.api.deps import RequireAuth

api_router = APIRouter()
# Open: health, auth, setup and settings (which protects its own routes).
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(setup.router)

# Everything else needs a login unless `auth.mode` is "none".
protected = APIRouter(dependencies=[RequireAuth])
for module in (
    categories,
    location_types,
    locations,
    barcodes,
    items,
    units,
    stock,
    packs,
    logs,
    attachments,
    purchase,
    scan,
    search,
    trash,
):
    protected.include_router(module.router)
api_router.include_router(protected)
