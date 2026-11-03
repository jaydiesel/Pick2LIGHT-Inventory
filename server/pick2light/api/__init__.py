from fastapi import APIRouter

from pick2light.api import (
    attachments,
    auth,
    backups,
    barcodes,
    categories,
    health,
    io,
    items,
    labels,
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
api_router.include_router(packs.list_router)

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
    labels,
    purchase,
    scan,
    search,
    trash,
    io,
    backups,
):
    protected.include_router(module.router)
api_router.include_router(protected)
