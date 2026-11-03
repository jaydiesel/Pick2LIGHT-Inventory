"""Password hashing, session tokens and the single application user."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import ValidationFailed
from pick2light.models import AppUser

MIN_PASSWORD_LENGTH = 8
SESSION_MAX_AGE_S = 30 * 24 * 3600
_SALT = "p2l-session"
_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash: str, pw: str) -> bool:
    try:
        return _hasher.verify(hash, pw)
    except (VerificationError, InvalidHashError):
        return False


def make_session_token(secret: str, user_id: int) -> str:
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps(user_id)


def read_session_token(secret: str, token: str, max_age_s: int = SESSION_MAX_AGE_S) -> int | None:
    try:
        value = URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=max_age_s)
    except BadSignature:  # includes SignatureExpired
        return None
    return value if type(value) is int else None


async def get_user(db: AsyncSession) -> AppUser | None:
    return await db.scalar(select(AppUser).order_by(AppUser.id).limit(1))


def check_new_password(password: str, field: str = "password") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed({field: f"must be at least {MIN_PASSWORD_LENGTH} characters"})


async def set_password(db: AsyncSession, username: str, password: str) -> AppUser:
    """Create the single user, or change the existing user's name and password."""
    check_new_password(password)
    if not username.strip():
        raise ValidationFailed({"username": "must not be empty"})
    user = await get_user(db)
    if user is None:
        user = AppUser(username=username.strip(), password_hash=hash_password(password))
        db.add(user)
    else:
        user.username = username.strip()
        user.password_hash = hash_password(password)
    await db.flush()
    return user
