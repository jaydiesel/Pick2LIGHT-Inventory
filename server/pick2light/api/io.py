import json
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from pick2light.api.deps import DB
from pick2light.core import csv_io
from pick2light.core.csv_io import Entity, ImportOptions, ImportPreview
from pick2light.errors import ValidationFailed

router = APIRouter(tags=["import/export"])


@router.get("/export/full.json")
async def export_full(db: DB) -> Response:
    body = json.dumps(await csv_io.export_full_json(db), ensure_ascii=False, default=str)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="pick2light-full.json"'},
    )


@router.get("/export/{entity}.csv")
async def export_entity(entity: Entity, db: DB) -> StreamingResponse:
    return StreamingResponse(
        csv_io.export_csv(db, entity),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{entity}.csv"'},
    )


def _options(raw: str) -> ImportOptions:
    try:
        return ImportOptions.model_validate_json(raw)
    except ValidationError as exc:
        fields = {".".join(str(p) for p in e["loc"]) or "options": e["msg"] for e in exc.errors()}
        raise ValidationFailed({"options": "invalid options", **fields}) from None


@router.post("/import/csv/preview")
async def preview(
    db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]
) -> ImportPreview:
    return await csv_io.preview_import(db, await file.read(), _options(options))


@router.post("/import/csv/apply")
async def apply(
    db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]
) -> ImportPreview:
    return await csv_io.apply_import(db, await file.read(), _options(options))
