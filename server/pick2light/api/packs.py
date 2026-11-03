from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from pick2light.api.deps import DB, require_auth_unless_setup_pending
from pick2light.core import packs as svc
from pick2light.core.packs import Pack, PackResult, PackSummary
from pick2light.errors import ValidationFailed

router = APIRouter(tags=["packs"])
# Mounted outside the protected group: the setup wizard lists packs before anyone can log in.
list_router = APIRouter(tags=["packs"], dependencies=[Depends(require_auth_unless_setup_pending)])


class ApplyPack(BaseModel):
    pack_id: str | None = None
    pack: Pack | None = None
    parent_id: int | None = None


@list_router.get("/packs")
async def list_packs() -> list[PackSummary]:
    return svc.list_builtin_packs()


@router.post("/packs/apply")
async def apply_pack(data: ApplyPack, db: DB) -> PackResult:
    if (data.pack_id is None) == (data.pack is None):
        raise ValidationFailed({"pack_id": "give exactly one of pack_id and pack"})
    pack = svc.load_builtin_pack(data.pack_id) if data.pack_id is not None else data.pack
    assert pack is not None
    return await svc.apply_pack(db, pack, data.parent_id)


@router.post("/packs/import")
async def import_pack(file: UploadFile, db: DB, parent_id: int | None = None) -> PackResult:
    pack = svc.parse_pack(await file.read())
    return await svc.apply_pack(db, pack, parent_id)


@router.get("/categories/{category_id}/export-pack")
async def export_pack(category_id: int, db: DB) -> Pack:
    return await svc.export_pack(db, category_id)
