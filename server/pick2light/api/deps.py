from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.core.auth import SESSION_MAX_AGE_S, make_session_token, read_session_token
from pick2light.core.settings import get_setting
from pick2light.db import get_db
from pick2light.models import AppUser

DB = Annotated[AsyncSession, Depends(get_db)]

SESSION_COOKIE = "p2l_session"


def set_session_cookie(response: Response, secret_key: str, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(secret_key, user_id),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        path="/",
    )


async def is_authenticated(request: Request, db: AsyncSession) -> bool:
    """True when auth is off, or the request carries a valid session cookie."""
    if await get_setting(db, "auth.mode") == "none":
        return True
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    user_id = read_session_token(request.app.state.settings.secret_key, token)
    return user_id is not None and await db.get(AppUser, user_id) is not None


async def require_auth(request: Request, db: DB) -> None:
    if not await is_authenticated(request, db):
        raise HTTPException(status_code=401, detail="Login required")


RequireAuth = Depends(require_auth)


async def require_auth_unless_setup_pending(request: Request, db: DB) -> None:
    """Open while the first-run wizard has not finished (it needs to list starter packs)."""
    if not await get_setting(db, "setup.completed"):
        return
    await require_auth(request, db)
