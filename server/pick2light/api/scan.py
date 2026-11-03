from fastapi import APIRouter, Request, Response

from pick2light.api.deps import DB
from pick2light.core.scan import ScanRequest, ScanResult, handle_scan

router = APIRouter(tags=["scan"])


@router.post("/scan")
async def scan(data: ScanRequest, request: Request, db: DB) -> ScanResult:
    return await handle_scan(db, data, request.app.state.recent_unknown)


@router.get("/scan/unknown")
async def recent_unknown(request: Request) -> list[str]:
    return list(reversed(request.app.state.recent_unknown))


@router.delete("/scan/unknown/{code:path}", status_code=204)
async def forget_unknown(code: str, request: Request) -> Response:
    recent = request.app.state.recent_unknown
    if code in recent:
        recent.remove(code)
    return Response(status_code=204)
