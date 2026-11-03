from fastapi import APIRouter, Request, Response

from pick2light.api.deps import DB
from pick2light.core import scan as svc
from pick2light.core.scan import ScanRequest, ScanResult

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("")
async def scan(data: ScanRequest, db: DB, request: Request) -> ScanResult:
    return await svc.handle_scan(db, data, request.app.state.recent_unknown)


@router.get("/unknown")
async def recent_unknown(request: Request) -> list[str]:
    """Unrecognised codes, newest first, without repeats."""
    return list(reversed(request.app.state.recent_unknown))


@router.delete("/unknown/{code}", status_code=204)
async def forget_unknown(code: str, request: Request) -> Response:
    codes = request.app.state.recent_unknown
    while code in codes:
        codes.remove(code)
    return Response(status_code=204)
