"""Settings registry with typed defaults (spec §10.1 Settings)."""

import re
from fnmatch import fnmatch
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.errors import InvalidOperation, ValidationFailed
from pick2light.models import AppUser, SettingRow

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
PUBLIC_KEYS = ("auth.mode", "setup.completed", "display.theme", "scanner.*")
CHOICES = {
    "auth.mode": ("password", "none"),
    "lights.light_children_default": ("on", "off"),
    "display.theme": ("system", "light", "dark"),
}
_SCHEDULE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


async def get_all(db: AsyncSession) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in await db.scalars(select(SettingRow)):
        if row.key in DEFAULTS:
            values[row.key] = row.value
    return values


async def get_setting(db: AsyncSession, key: str) -> Any:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = await db.get(SettingRow, key)
    return row.value if row is not None else DEFAULTS[key]


async def public_settings(db: AsyncSession) -> dict[str, Any]:
    return {k: v for k, v in (await get_all(db)).items() if any(fnmatch(k, p) for p in PUBLIC_KEYS)}


def _check(key: str, value: Any) -> str | None:
    if key not in DEFAULTS:
        return "unknown setting"
    default = DEFAULTS[key]
    if type(value) is not type(default):
        return f"Must be {type(default).__name__.replace('str', 'text').replace('int', 'a whole number').replace('bool', 'true or false')}"
    if key in CHOICES and value not in CHOICES[key]:
        return f"Must be one of: {', '.join(CHOICES[key])}"
    if key == "backup.schedule" and not _SCHEDULE.match(value):
        return "Use 24-hour HH:MM, e.g. 03:00"
    if isinstance(default, int) and not isinstance(default, bool) and value < 1:
        return "Must be at least 1"
    return None


async def set_settings(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    errors = {k: msg for k, v in values.items() if (msg := _check(k, v))}
    if errors:
        raise ValidationFailed(errors)
    if values.get("auth.mode") == "password" and await db.scalar(select(AppUser.id).limit(1)) is None:
        raise InvalidOperation("Set a password before turning the login on")
    for key, value in values.items():
        await db.execute(
            pg_insert(SettingRow)
            .values(key=key, value=value)
            .on_conflict_do_update(index_elements=["key"], set_={"value": value})
        )
    await db.flush()
    return await get_all(db)
