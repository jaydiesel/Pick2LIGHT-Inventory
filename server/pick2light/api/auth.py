from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from pick2light.api.deps import DB, is_authenticated
from pick2light.core import auth as svc
from pick2light.core.settings import get_setting
from pick2light.errors import Unauthenticated

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    current: str | None = None
    new: str
    username: str | None = None


class AuthStatus(BaseModel):
    mode: str
    authenticated: bool
    setup_completed: bool
    username: str | None


def set_session_cookie(response: Response, request: Request, user_id: int) -> None:
    token = svc.make_session_token(request.app.state.settings.resolved_secret_key(), user_id)
    response.set_cookie(svc.COOKIE, token, max_age=svc.MAX_AGE_S, httponly=True, samesite="lax", path="/")


@router.get("/auth/status")
async def status(request: Request, db: DB) -> AuthStatus:
    mode = await get_setting(db, "auth.mode")
    user = await svc.get_user(db)
    authed = mode == "none" or await is_authenticated(request, db)
    return AuthStatus(
        mode=mode,
        authenticated=authed,
        setup_completed=await get_setting(db, "setup.completed"),
        username=user.username if user and authed else None,
    )


@router.post("/auth/login")
async def login(data: LoginIn, request: Request, response: Response, db: DB) -> AuthStatus:
    user = await svc.authenticate(db, data.username, data.password)
    if user is None:
        raise Unauthenticated("Wrong username or password")
    set_session_cookie(response, request, user.id)
    return AuthStatus(
        mode=await get_setting(db, "auth.mode"),
        authenticated=True,
        setup_completed=await get_setting(db, "setup.completed"),
        username=user.username,
    )


@router.post("/auth/logout", status_code=204)
async def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(svc.COOKIE, path="/")
    return response


@router.post("/auth/password", status_code=204)
async def change_password(data: PasswordIn, db: DB) -> Response:
    user = await svc.get_user(db)
    if user is not None and not svc.verify_password(user.password_hash, data.current or ""):
        raise Unauthenticated("The current password is wrong")
    await svc.set_password(db, data.username or (user.username if user else "admin"), data.new)
    return Response(status_code=204)
