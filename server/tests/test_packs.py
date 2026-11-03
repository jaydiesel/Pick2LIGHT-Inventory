import json
import re

import pytest
from sqlalchemy import select

from pick2light.core import packs
from pick2light.core.categories import (
    KEY_PATTERN,
    CategoryIn,
    FieldDefIn,
    LogEntryTypeIn,
    add_field,
    create_category,
    create_log_type,
    effective_field_defs,
    effective_log_types,
    effective_tracking_mode,
)
from pick2light.errors import NotFound
from pick2light.models import Category
from tests.factories import make_category, make_item, make_unit

BUILTIN = ["electronics", "hardware", "batteries", "computer", "generic"]


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def test_builtin_packs_valid():
    summaries = packs.list_builtin_packs()
    assert sorted(s.id for s in summaries) == sorted(BUILTIN)
    assert all(s.category_count >= 1 and s.name and s.description for s in summaries)
    key_re = re.compile(KEY_PATTERN)
    for summary in summaries:
        pack = packs.load_builtin_pack(summary.id)
        assert pack.id == summary.id
        for node in _walk(pack.categories):
            keys = [f.key for f in node.fields]
            assert len(keys) == len(set(keys))
            assert all(key_re.match(k) for k in keys)
            for log_type in node.log_types:
                assert key_re.match(log_type.key)
                assert all(key_re.match(f.key) for f in log_type.fields)


def test_unknown_pack():
    with pytest.raises(NotFound):
        packs.load_builtin_pack("nope")


async def _by_name(db, name):
    return await db.scalar(select(Category).where(Category.name == name))


async def test_apply_batteries_pack(db):
    result = await packs.apply_pack(db, packs.load_builtin_pack("batteries"))
    assert result.created == 2
    assert result.skipped == 0
    cells = await _by_name(db, "Li-ion Cells")
    assert cells.tracking_mode == "unit"
    item = await make_item(db, cells, "Samsung 30Q", attrs={"format": "18650", "model": "30Q"})
    assert item.sku == "CELL-18650-30Q"
    unit = await make_unit(db, item)
    assert unit.unit_code == "C0001"
    log_types = await effective_log_types(db, cells.id)
    assert [t.key for t in log_types] == ["capacity_test"]
    assert log_types[0].applies_to == "unit"
    assert log_types[0].summary_fields == ["capacity_mah", "ir_mohm", "storage_v"]
    scopes = {f.key: f.scope for f in await effective_field_defs(db, cells.id)}
    assert scopes["wrap_color"] == "unit" and scopes["source"] == "unit"
    assert scopes["format"] == "item"


async def test_hardware_screw_sku(db):
    await packs.apply_pack(db, packs.load_builtin_pack("hardware"))
    screws = await _by_name(db, "Screws/Bolts")
    item = await make_item(
        db, screws, "M3x10 SHCS", attrs={"thread": "M3", "length": 10, "head": "socket_head"}
    )
    assert item.sku == "SCR-M3-10-SHCS"
    imperial = await make_item(
        db, screws, "#4-40", attrs={"thread": "#4-40", "length": 6, "head": "pan_head"}
    )
    assert imperial.sku == "SCR-4-40-6-PH"


async def test_electronics_si_sku(db):
    await packs.apply_pack(db, packs.load_builtin_pack("electronics"))
    resistors = await _by_name(db, "Resistors")
    item = await make_item(db, resistors, "4k7", attrs={"resistance": 4700, "package": "0603"})
    assert item.sku == "RES-4.7k-0603"


async def test_computer_pack_all_unit_tracked(db):
    await packs.apply_pack(db, packs.load_builtin_pack("computer"))
    for name in ("Computer", "RAM", "CPUs", "PCIe Cards", "Drives", "Peripherals"):
        cat = await _by_name(db, name)
        assert await effective_tracking_mode(db, cat.id) == "unit", name


async def test_bulk_packs_effective_bulk(db):
    for pack_id in ("electronics", "hardware"):
        await packs.apply_pack(db, packs.load_builtin_pack(pack_id))
    for name in ("Resistors", "Modules", "Screws/Bolts", "Wire", "Connectors"):
        cat = await _by_name(db, name)
        assert await effective_tracking_mode(db, cat.id) == "bulk", name


async def test_export_child_is_standalone(db):
    await packs.apply_pack(db, packs.load_builtin_pack("computer"))
    computer = await _by_name(db, "Computer")
    await add_field(
        db, computer.id, FieldDefIn(key="shelf_note", label="Note", type="text", scope="unit")
    )
    await create_log_type(
        db, computer.id, LogEntryTypeIn(key="inspection", name="Inspection", applies_to="unit")
    )
    ram = await _by_name(db, "RAM")
    exported = packs.Pack.model_validate_json(
        (await packs.export_pack(db, ram.id)).model_dump_json()
    )
    assert exported.categories[0].tracking_mode == "unit"

    result = await packs.apply_pack(db, exported)
    assert result.created == 1
    copy = await db.scalar(
        select(Category).where(Category.name == "RAM", Category.parent_id.is_(None))
    )
    assert await effective_tracking_mode(db, copy.id) == "unit"
    fields = {f.key: f.scope for f in await effective_field_defs(db, copy.id)}
    assert fields["shelf_note"] == "unit"
    assert "gen" in fields
    assert {t.key for t in await effective_log_types(db, copy.id)} == {"memtest", "inspection"}


async def test_apply_twice_skips(db):
    pack = packs.load_builtin_pack("batteries")
    await packs.apply_pack(db, pack)
    again = await packs.apply_pack(db, pack)
    assert again.created == 0
    assert again.skipped == 2
    count = len(list(await db.scalars(select(Category).where(Category.name == "Li-ion Cells"))))
    assert count == 1
    cells = await _by_name(db, "Li-ion Cells")
    keys = [f.key for f in await effective_field_defs(db, cells.id)]
    assert len(keys) == len(set(keys))


async def test_apply_skips_existing_but_processes_children(db):
    existing = await create_category(db, CategoryIn(name="Batteries"))
    result = await packs.apply_pack(db, packs.load_builtin_pack("batteries"))
    assert (result.created, result.skipped) == (1, 1)
    cells = await _by_name(db, "Li-ion Cells")
    assert cells.parent_id == existing.id


async def test_apply_all_builtin_packs(db):
    for pack_id in BUILTIN:
        await packs.apply_pack(db, packs.load_builtin_pack(pack_id))


async def test_export_roundtrip(db):
    await packs.apply_pack(db, packs.load_builtin_pack("batteries"))
    batteries = await _by_name(db, "Batteries")
    exported = await packs.export_pack(db, batteries.id)
    assert exported.location_types == []
    assert exported.categories[0].name == "Batteries"
    # Round-trips through JSON as well.
    exported = packs.Pack.model_validate(json.loads(exported.model_dump_json()))

    target = await make_category(db, "Imported")
    result = await packs.apply_pack(db, exported, parent_id=target.id)
    assert result.created == 2
    copies = list(await db.scalars(select(Category).where(Category.name == "Li-ion Cells")))
    assert len(copies) == 2
    original, copy = sorted(copies, key=lambda c: c.id)
    orig_fields = [f.key for f in await effective_field_defs(db, original.id)]
    copy_fields = [f.key for f in await effective_field_defs(db, copy.id)]
    assert orig_fields == copy_fields and "capacity_mah" not in copy_fields
    assert [t.key for t in await effective_log_types(db, copy.id)] == ["capacity_test"]
    assert copy.sku_pattern == "CELL-{format}-{model}"
    assert copy.tracking_mode == "unit"
