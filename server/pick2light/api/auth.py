from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from pick2light.api.deps import DB, SESSION_COOKIE, RequireAuth, is_authenticated
from pick2light.core import auth
from pick2light.core.settings import get_setting
from pick2light.errors import InvalidOperation, ValidationFailed

router = APIRouter(prefix="/auth", tags=["auth"])


class Status(BaseModel):
    mode: str
    authenticated: bool
    setup_completed: bool


class Login(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


class Ok(BaseModel):
    ok: bool = True


@router.get("/status")
async def status(request: Request, db: DB) -> Status:
    return Status(
        mode=await get_setting(db, "auth.mode"),
        authenticated=await is_authenticated(request, db),
        setup_completed=await get_setting(db, "setup.completed"),
    )


@router.post("/login")
async def login(body: Login, request: Request, response: Response, db: DB) -> Ok:
    if await get_setting(db, "auth.mode") == "none":
        return Ok()
    user = await auth.get_user(db)
    if (
        user is None
        or user.username != body.username
        or not auth.verify_password(user.password_hash, body.password)
    ):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    response.set_cookie(
        SESSION_COOKIE,
        auth.make_session_token(request.app.state.settings.secret_key, user.id),
        max_age=auth.SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return Ok()


@router.post("/logout")
async def logout(response: Response) -> Ok:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return Ok()


@router.post("/password", dependencies=[RequireAuth])
async def change_password(body: PasswordChange, db: DB) -> Ok:
    user = await auth.get_user(db)
    if user is None:
        raise InvalidOperation("No password has been set yet")
    if not auth.verify_password(user.password_hash, body.current):
        raise ValidationFailed({"current": "incorrect password"})
    await auth.set_password(db, user.username, body.new)
    return Ok()
