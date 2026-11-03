from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import logs as svc
from pick2light.core.logs import LatestOut, LogEntryIn, LogEntryOut, LogEntryPatch

router = APIRouter(tags=["log"])


@router.get("/units/{unit_id}/log")
async def unit_log(unit_id: int, db: DB) -> list[LogEntryOut]:
    return await svc.list_log_entries(db, unit_id=unit_id)


@router.get("/items/{item_id}/log")
async def item_log(item_id: int, db: DB) -> list[LogEntryOut]:
    return await svc.list_log_entries(db, item_id=item_id)


@router.get("/units/{unit_id}/latest")
async def unit_latest(unit_id: int, db: DB) -> dict[str, LatestOut]:
    return await svc.latest_values(db, unit_id=unit_id)


@router.get("/items/{item_id}/latest")
async def item_latest(item_id: int, db: DB) -> dict[str, LatestOut]:
    return await svc.latest_values(db, item_id=item_id)


@router.post("/log-entries", status_code=201)
async def add_entry(data: LogEntryIn, db: DB) -> LogEntryOut:
    return await svc.to_out(db, await svc.add_log_entry(db, data))


@router.patch("/log-entries/{entry_id}")
async def update_entry(entry_id: int, data: LogEntryPatch, db: DB) -> LogEntryOut:
    return await svc.to_out(db, await svc.update_log_entry(db, entry_id, data))


@router.delete("/log-entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db: DB) -> Response:
    await svc.delete_log_entry(db, entry_id)
    return Response(status_code=204)
