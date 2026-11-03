import pytest

from pick2light.core.settings import DEFAULTS, get_all, get_setting, public_settings, set_settings
from pick2light.errors import InvalidOperation, ValidationFailed


async def test_defaults_returned(db):
    assert await get_setting(db, "scanner.max_gap_ms") == 30
    values = await get_all(db)
    assert values["backup.keep"] == 14 and values["auth.mode"] == "password"
    assert set(DEFAULTS) <= set(values)


async def test_set_and_read_back(db):
    await set_settings(db, {"trash.retention_days": 7, "scanner.prefix": "#"})
    assert await get_setting(db, "trash.retention_days") == 7
    assert await get_setting(db, "scanner.prefix") == "#"


async def test_unknown_key_rejected(db):
    with pytest.raises(ValidationFailed) as e:
        await set_settings(db, {"colour": "red"})
    assert e.value.fields == {"colour": "unknown setting"}


async def test_type_mismatch_rejected(db):
    with pytest.raises(ValidationFailed) as e:
        await set_settings(db, {"backup.keep": "many", "scanner.intercept_inputs": 1})
    assert set(e.value.fields) == {"backup.keep", "scanner.intercept_inputs"}


async def test_schedule_format(db):
    with pytest.raises(ValidationFailed):
        await set_settings(db, {"backup.schedule": "25:00"})
    await set_settings(db, {"backup.schedule": "02:30"})


async def test_choice_and_min_values(db):
    with pytest.raises(ValidationFailed):
        await set_settings(db, {"lights.light_children_default": "maybe"})
    with pytest.raises(ValidationFailed):
        await set_settings(db, {"backup.keep": 0})


async def test_password_mode_requires_password(db):
    await set_settings(db, {"auth.mode": "none"})
    with pytest.raises(InvalidOperation):
        await set_settings(db, {"auth.mode": "password"})


async def test_public_settings_subset(db):
    pub = await public_settings(db)
    assert "scanner.max_gap_ms" in pub and "auth.mode" in pub
    assert "backup.keep" not in pub
