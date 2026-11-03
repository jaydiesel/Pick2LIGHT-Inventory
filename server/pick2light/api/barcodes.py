from fastapi import APIRouter, Response

from pick2light.api.deps import DB
from pick2light.core import barcodes as svc
from pick2light.core.barcodes import BarcodeIn, BarcodeOut
from pick2light.errors import NotFound

router = APIRouter(tags=["barcodes"])


@router.get("/barcodes/{code:path}")
async def lookup(code: str, db: DB) -> BarcodeOut:
    bc = await svc.lookup_barcode(db, code)
    if bc is None:
        raise NotFound(f"No item, unit or location has the code '{code}'")
    return BarcodeOut.model_validate(bc)


@router.post("/barcodes", status_code=201)
async def add_barcode(data: BarcodeIn, db: DB) -> BarcodeOut:
    return BarcodeOut.model_validate(await svc.add_barcode(db, data))


@router.delete("/barcodes/{barcode_id}", status_code=204)
async def delete_barcode(barcode_id: int, db: DB) -> Response:
    await svc.delete_barcode(db, barcode_id)
    return Response(status_code=204)
