"""Settings registry: typed defaults, validation, and storage as key/value JSON rows."""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from pick2light.errors import InvalidOperation, ValidationFailed
from pick2light.models import AppUser, Setting

DEFAULTS: dict[str, Any] = {
    "auth.mode": "password",
    "scanner.min_length": 4,
    "scanner.max_gap_ms": 30,
    "scanner.prefix": "",
    "scanner.suffix": "",
    "scanner.intercept_inputs": True,
    "lights.light_children_default": "off",
    "trash.retention_days": 30,
    "backup.schedule": "03:00",
    "backup.keep": 14,
    "display.theme": "system",
    "setup.completed": False,
}

# Readable without login; an entry ending in ".*" matches by prefix.
PUBLIC_KEYS = {"auth.mode", "setup.completed", "display.theme", "scanner.*"}

_CHOICES = {
    "auth.mode": ("password", "none"),
    "lights.light_children_default": ("on", "off"),
}
_SCHEDULE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def is_public(key: str) -> bool:
    return any(
        key.startswith(pattern[:-1]) if pattern.endswith("*") else key == pattern
        for pattern in PUBLIC_KEYS
    )


def _problem(key: str, value: Any) -> str | None:
    default = DEFAULTS[key]
    # type() rather than isinstance: a bool is not an int setting, nor the reverse.
    if type(value) is not type(default):
        return f"must be {type(default).__name__}"
    if key in _CHOICES and value not in _CHOICES[key]:
        return "must be one of " + ", ".join(_CHOICES[key])
    if key == "backup.schedule" and not _SCHEDULE.match(value):
        return "must be a time of day as HH:MM"
    if type(default) is int and value < 1:
        return "must be at least 1"
    return None


async def _stored(db: AsyncSession) -> dict[str, Any]:
    return {row.key: row.value for row in await db.scalars(select(Setting))}


async def get_all(db: AsyncSession) -> dict[str, Any]:
    return {**DEFAULTS, **{k: v for k, v in (await _stored(db)).items() if k in DEFAULTS}}


async def get_setting(db: AsyncSession, key: str) -> Any:
    if key not in DEFAULTS:
        raise ValidationFailed({key: "unknown setting"})
    stored = await db.scalar(select(Setting.value).where(Setting.key == key))
    return DEFAULTS[key] if stored is None else stored


async def set_settings(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and store ``values`` (all or nothing); return every setting."""
    errors: dict[str, str] = {}
    for key, value in values.items():
        if key not in DEFAULTS:
            errors[key] = "unknown setting"
        elif (problem := _problem(key, value)) is not None:
            errors[key] = problem
    if errors:
        raise ValidationFailed(errors)
    if (
        values.get("auth.mode") == "password"
        and await db.scalar(select(AppUser.id).limit(1)) is None
    ):
        raise InvalidOperation("Set a password before turning on password login")
    for key, value in values.items():
        stmt = insert(Setting).values(key=key, value=value)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[Setting.key],
                set_={"value": stmt.excluded.value, "updated_at": func.now()},
            )
        )
    await db.flush()
    return await get_all(db)
