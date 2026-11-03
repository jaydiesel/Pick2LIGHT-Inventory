from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.auth import COOKIE, read_session_token
from pick2light.core.settings import get_setting
from pick2light.db import get_db
from pick2light.errors import Unauthenticated
from pick2light.models import AppUser

DB = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def is_authenticated(request: Request, db: AsyncSession) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    user_id = read_session_token(request.app.state.settings.resolved_secret_key(), token)
    return user_id is not None and await db.get(AppUser, user_id) is not None


async def require_auth(request: Request, db: DB) -> None:
    if await get_setting(db, "auth.mode") == "none":
        return
    if not await is_authenticated(request, db):
        raise Unauthenticated("Please log in")
