"""Optional single-user password login (spec §10.3)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import ValidationFailed
from pick2light.models import AppUser

COOKIE = "p2l_session"
MAX_AGE_S = 30 * 24 * 3600
_SALT = "p2l-session"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def make_session_token(secret: str, user_id: int) -> str:
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps(user_id)


def read_session_token(secret: str, token: str, max_age_s: int = MAX_AGE_S) -> int | None:
    try:
        value = URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=max_age_s)
    except BadSignature:
        return None
    return value if isinstance(value, int) else None


async def get_user(db: AsyncSession) -> AppUser | None:
    return await db.scalar(select(AppUser).order_by(AppUser.id).limit(1))


async def set_password(db: AsyncSession, username: str, password: str) -> AppUser:
    errors: dict[str, str] = {}
    if len(password) < 8:
        errors["password"] = "At least 8 characters"
    if not username.strip():
        errors["username"] = "Required"
    if errors:
        raise ValidationFailed(errors)
    user = await get_user(db)
    if user is None:
        user = AppUser(username=username.strip(), password_hash=hash_password(password))
        db.add(user)
    else:
        user.username = username.strip()
        user.password_hash = hash_password(password)
    await db.flush()
    return user


async def authenticate(db: AsyncSession, username: str, password: str) -> AppUser | None:
    user = await get_user(db)
    if user is None or user.username != username.strip() or not verify_password(user.password_hash, password):
        return None
    return user
