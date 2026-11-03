import pytest

from pick2light.core.settings import DEFAULTS, PUBLIC_KEYS, get_all, get_setting, set_settings
from pick2light.errors import InvalidOperation, ValidationFailed


async def test_defaults_returned(db):
    assert await get_all(db) == DEFAULTS
    assert await get_setting(db, "trash.retention_days") == 30
    assert DEFAULTS["auth.mode"] == "password"
    assert "scanner.*" in PUBLIC_KEYS


async def test_values_are_stored_and_merged(db):
    result = await set_settings(db, {"backup.keep": 3, "display.theme": "dark"})
    assert result["backup.keep"] == 3
    assert (await get_all(db))["display.theme"] == "dark"
    await set_settings(db, {"backup.keep": 5})
    assert await get_setting(db, "backup.keep") == 5
    assert (await get_all(db))["scanner.min_length"] == 4


async def test_unknown_key_rejected(db):
    with pytest.raises(ValidationFailed) as exc:
        await set_settings(db, {"nope": 1})
    assert exc.value.fields == {"nope": "unknown setting"}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("backup.keep", "14"),
        ("backup.keep", True),
        ("scanner.intercept_inputs", 1),
        ("scanner.prefix", 5),
        ("backup.keep", 0),
        ("auth.mode", "ldap"),
        ("lights.light_children_default", "maybe"),
    ],
)
async def test_type_mismatch_rejected(db, key, value):
    with pytest.raises(ValidationFailed) as exc:
        await set_settings(db, {key: value})
    assert key in exc.value.fields


@pytest.mark.parametrize("value", ["3:00", "24:00", "03:60", "0300", "", "ab:cd"])
async def test_schedule_format(db, value):
    with pytest.raises(ValidationFailed):
        await set_settings(db, {"backup.schedule": value})


async def test_valid_schedule(db):
    await set_settings(db, {"backup.schedule": "23:59"})
    assert await get_setting(db, "backup.schedule") == "23:59"


async def test_nothing_saved_when_any_value_invalid(db):
    with pytest.raises(ValidationFailed):
        await set_settings(db, {"backup.keep": 2, "nope": 1})
    assert await get_setting(db, "backup.keep") == 14


async def test_password_mode_requires_password(db):
    await set_settings(db, {"auth.mode": "none"})
    with pytest.raises(InvalidOperation):
        await set_settings(db, {"auth.mode": "password"})
