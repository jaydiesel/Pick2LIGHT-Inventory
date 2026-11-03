from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from pick2light.api.deps import DB, set_session_cookie
from pick2light.core import auth
from pick2light.core import packs as pack_svc
from pick2light.core.settings import get_setting, set_settings
from pick2light.errors import Conflict, ValidationFailed
from pick2light.models import LocationType

router = APIRouter(prefix="/setup", tags=["setup"])

DEFAULT_LOCATION_TYPES = ("Room", "Cabinet", "Drawer", "Shelf", "Bin", "Tote", "Box")


class SetupIn(BaseModel):
    auth_mode: Literal["password", "none"]
    username: str = "admin"
    password: str | None = None
    packs: list[str] = []


class SetupOut(BaseModel):
    ok: bool = True
    categories_created: int


@router.post("")
async def run_setup(body: SetupIn, request: Request, response: Response, db: DB) -> SetupOut:
    """First-run wizard: unauthenticated, and only until `setup.completed` is set."""
    if await get_setting(db, "setup.completed"):
        raise Conflict("Setup has already been completed")
    if body.auth_mode == "password" and not body.password:
        raise ValidationFailed({"password": "required for password login"})
    chosen = [pack_svc.load_builtin_pack(pack_id) for pack_id in body.packs]  # 404 before writes

    user = None
    if body.auth_mode == "password":
        assert body.password is not None
        user = await auth.set_password(db, body.username, body.password)  # before auth.mode
    await set_settings(db, {"auth.mode": body.auth_mode})

    existing = set(await db.scalars(select(LocationType.name)))
    for name in DEFAULT_LOCATION_TYPES:
        if name not in existing:
            db.add(LocationType(name=name))
    created = 0
    for pack in chosen:
        created += (await pack_svc.apply_pack(db, pack)).created
    await set_settings(db, {"setup.completed": True})

    if user is not None:
        set_session_cookie(response, request.app.state.settings.secret_key, user.id)
    return SetupOut(categories_created=created)
