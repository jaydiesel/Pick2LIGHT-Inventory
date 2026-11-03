from factories import make_category, make_item, make_unit

from pick2light.core.categories import KEY_RE, effective_tracking_mode, field_defs_out, list_categories
from pick2light.core.packs import apply_pack, export_pack, list_builtin_packs, load_builtin_pack


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.children)


async def _cat(db, name):
    return next(c for c in await list_categories(db) if c.name == name)


def test_builtin_packs_valid():
    summaries = list_builtin_packs()
    assert {s.id for s in summaries} == {"electronics", "hardware", "batteries", "computer", "generic"}
    for s in summaries:
        pack = load_builtin_pack(s.id)
        assert s.category_count == len(list(_walk(pack.categories)))
        for node in _walk(pack.categories):
            for f in node.fields:
                assert KEY_RE.match(f.key), f.key
            for lt in node.log_types:
                assert KEY_RE.match(lt.key), lt.key


async def test_apply_batteries_pack(db):
    result = await apply_pack(db, load_builtin_pack("batteries"))
    assert result.created == 2 and result.skipped == 0
    cells = await _cat(db, "Li-ion Cells")
    assert await effective_tracking_mode(db, cells.id) == "unit"
    item = await make_item(db, cells, "Samsung 30Q", attrs={"format": "18650", "model": "30Q"})
    assert item.sku == "CELL-18650-30Q"
    assert (await make_unit(db, item)).unit_code == "C0001"


async def test_hardware_screw_sku(db):
    await apply_pack(db, load_builtin_pack("hardware"))
    screws = await _cat(db, "Screws & Bolts")
    item = await make_item(
        db, screws, "M3x10 SHCS", attrs={"thread": "M3", "length": 10, "head": "socket_head"}
    )
    assert item.sku == "SCR-M3-10-SHCS"


async def test_electronics_resistor_sku(db):
    await apply_pack(db, load_builtin_pack("electronics"))
    res = await _cat(db, "Resistors")
    item = await make_item(db, res, "4k7 0805", attrs={"resistance": "4k7", "package": "0805"})
    assert item.sku == "RES-4.7k-0805"


async def test_apply_twice_skips(db):
    pack = load_builtin_pack("computer")
    first = await apply_pack(db, pack)
    second = await apply_pack(db, pack)
    assert second.created == 0 and second.skipped == first.created


async def test_export_roundtrip(db):
    await apply_pack(db, load_builtin_pack("batteries"))
    root = await _cat(db, "Batteries")
    exported = await export_pack(db, root.id)
    target = await make_category(db, "Copy")
    await apply_pack(db, exported, parent_id=target.id)
    copy_cells = next(
        c for c in await list_categories(db) if c.name == "Li-ion Cells" and c.path[0].name == "Copy"
    )
    original = await _cat(db, "Li-ion Cells")
    keys = lambda fs: sorted(f.key for f in fs)  # noqa: E731
    assert keys(await field_defs_out(db, copy_cells.id)) == keys(await field_defs_out(db, original.id))
