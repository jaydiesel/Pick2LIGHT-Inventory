from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import categories as svc
from pick2light.core.categories import (
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    FieldDefIn,
    FieldDefOut,
    FieldDefPatch,
    LogEntryTypeIn,
    LogEntryTypeOut,
    LogEntryTypePatch,
)

router = APIRouter(tags=["categories"])


@router.get("/categories")
async def list_categories(db: DB) -> list[CategoryOut]:
    return await svc.list_category_outs(db)


@router.post("/categories", status_code=201)
async def create_category(data: CategoryIn, db: DB) -> CategoryOut:
    return await svc.category_out(db, await svc.create_category(db, data))


@router.get("/categories/{category_id}")
async def get_category(category_id: int, db: DB) -> CategoryOut:
    return await svc.category_out(db, await svc.get_category(db, category_id))


@router.patch("/categories/{category_id}")
async def update_category(category_id: int, data: CategoryPatch, db: DB) -> CategoryOut:
    return await svc.category_out(db, await svc.update_category(db, category_id, data))


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, db: DB) -> Response:
    await svc.delete_category(db, category_id)
    return Response(status_code=204)


@router.get("/categories/{category_id}/fields")
async def list_fields(category_id: int, db: DB) -> list[FieldDefOut]:
    """Effective fields; `inherited_from` is the defining ancestor (null when defined here)."""
    result = []
    for field in await svc.effective_field_defs(db, category_id):
        out = FieldDefOut.model_validate(field)
        out.inherited_from = field.category_id if field.category_id != category_id else None
        result.append(out)
    return result


@router.post("/categories/{category_id}/fields", status_code=201)
async def add_field(category_id: int, data: FieldDefIn, db: DB) -> FieldDefOut:
    return FieldDefOut.model_validate(await svc.add_field(db, category_id, data))


@router.patch("/fields/{field_id}")
async def update_field(field_id: int, data: FieldDefPatch, db: DB) -> FieldDefOut:
    return FieldDefOut.model_validate(await svc.update_field(db, field_id, data))


@router.delete("/fields/{field_id}", status_code=204)
async def delete_field(field_id: int, db: DB) -> Response:
    await svc.delete_field(db, field_id)
    return Response(status_code=204)


@router.get("/categories/{category_id}/log-types")
async def list_log_types(category_id: int, db: DB) -> list[LogEntryTypeOut]:
    return [
        LogEntryTypeOut.model_validate(t) for t in await svc.effective_log_types(db, category_id)
    ]


@router.post("/categories/{category_id}/log-types", status_code=201)
async def create_log_type(category_id: int, data: LogEntryTypeIn, db: DB) -> LogEntryTypeOut:
    return LogEntryTypeOut.model_validate(await svc.create_log_type(db, category_id, data))


@router.patch("/log-types/{log_type_id}")
async def update_log_type(log_type_id: int, data: LogEntryTypePatch, db: DB) -> LogEntryTypeOut:
    return LogEntryTypeOut.model_validate(await svc.update_log_type(db, log_type_id, data))


@router.delete("/log-types/{log_type_id}", status_code=204)
async def delete_log_type(log_type_id: int, db: DB) -> Response:
    await svc.delete_log_type(db, log_type_id)
    return Response(status_code=204)
