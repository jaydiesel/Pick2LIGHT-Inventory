import json
from typing import Annotated, Literal

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import BaseModel, ValidationError

from pick2light.api.auth import AuthStatus, set_session_cookie
from pick2light.api.deps import DB
from pick2light.core import packs as svc
from pick2light.core.auth import set_password
from pick2light.core.packs import Pack, PackResult, PackSummary
from pick2light.core.settings import get_setting, set_settings
from pick2light.errors import Conflict, ValidationFailed

public_router = APIRouter(tags=["setup"])
router = APIRouter(tags=["setup"])


class SetupIn(BaseModel):
    auth_mode: Literal["password", "none"] = "password"
    username: str = "admin"
    password: str | None = None
    packs: list[str] = []


class ApplyIn(BaseModel):
    pack_id: str | None = None
    pack: Pack | None = None
    parent_id: int | None = None


@public_router.get("/packs")
async def list_packs() -> list[PackSummary]:
    return svc.list_builtin_packs()


@public_router.post("/setup")
async def setup(data: SetupIn, request: Request, response: Response, db: DB) -> AuthStatus:
    if await get_setting(db, "setup.completed"):
        raise Conflict("Setup has already been completed")
    user = None
    if data.auth_mode == "password":
        user = await set_password(db, data.username, data.password or "")
    await svc.seed_location_types(db)
    for pack_id in data.packs:
        await svc.apply_pack(db, svc.load_builtin_pack(pack_id))
    await set_settings(db, {"auth.mode": data.auth_mode, "setup.completed": True})
    if user is not None:
        set_session_cookie(response, request, user.id)
    return AuthStatus(
        mode=data.auth_mode,
        authenticated=True,
        setup_completed=True,
        username=user.username if user else None,
    )


@router.post("/packs/apply")
async def apply(data: ApplyIn, db: DB) -> PackResult:
    if (data.pack_id is None) == (data.pack is None):
        raise ValidationFailed({"pack_id": "Give either pack_id or pack"})
    pack = data.pack or svc.load_builtin_pack(data.pack_id or "")
    return await svc.apply_pack(db, pack, parent_id=data.parent_id)


@router.post("/packs/import")
async def import_pack(
    file: Annotated[UploadFile, File()], db: DB, parent_id: int | None = None
) -> PackResult:
    try:
        pack = Pack.model_validate(json.loads(await file.read()))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailed({"file": f"Not a valid pack file: {str(exc)[:200]}"}) from None
    return await svc.apply_pack(db, pack, parent_id=parent_id)


@router.get("/categories/{category_id}/export-pack")
async def export(category_id: int, db: DB) -> Pack:
    return await svc.export_pack(db, category_id)
