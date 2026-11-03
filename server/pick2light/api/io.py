import json
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from pick2light.api.deps import DB
from pick2light.core import csv_io as svc
from pick2light.core.csv_io import ImportOptions, ImportPreview
from pick2light.errors import NotFound, ValidationFailed

router = APIRouter(tags=["import-export"])
MAX_CSV_BYTES = 20 * 1024 * 1024


@router.get("/export/full.json")
async def export_full(db: DB) -> JSONResponse:
    data = await svc.export_full_json(db)
    return JSONResponse(
        data, headers={"Content-Disposition": 'attachment; filename="pick2light-export.json"'}
    )


@router.get("/export/{entity}.csv")
async def export_csv(entity: str, db: DB) -> StreamingResponse:
    if entity not in svc.ENTITIES:
        raise NotFound(f"Unknown export '{entity}'")
    body = "".join([chunk async for chunk in svc.export_csv(db, entity)])
    return StreamingResponse(
        iter([body.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pick2light-{entity}.csv"'},
    )


async def _read(file: UploadFile, options: str) -> tuple[bytes, ImportOptions]:
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise ValidationFailed({"file": "CSV files can be at most 20 MB"})
    try:
        opts = ImportOptions.model_validate(json.loads(options))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailed({"options": f"Invalid options: {str(exc)[:200]}"}) from None
    return data, opts


@router.post("/import/csv/preview")
async def preview(
    file: Annotated[UploadFile, File()], options: Annotated[str, Form()], db: DB
) -> ImportPreview:
    data, opts = await _read(file, options)
    return await svc.preview_import(db, data, opts)


@router.post("/import/csv/apply")
async def apply(
    file: Annotated[UploadFile, File()], options: Annotated[str, Form()], db: DB
) -> ImportPreview:
    data, opts = await _read(file, options)
    return await svc.apply_import(db, data, opts)
