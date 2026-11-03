import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from pick2light import __version__
from pick2light.config import Settings, get_settings
from pick2light.db import make_engine, make_sessionmaker
from pick2light.errors import AppError, NotFound, ValidationFailed

log = logging.getLogger("pick2light")
PURGE_INTERVAL_S = 24 * 3600
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _purge_loop(app: FastAPI) -> None:
    """Purge expired trash on start-up and then once a day."""
    from pick2light.core.settings import get_setting
    from pick2light.core.trash import purge_expired

    while True:
        try:
            async with app.state.sessionmaker() as db:
                days = await get_setting(db, "trash.retention_days")
                count = await purge_expired(db, days, root=app.state.settings.attachments_dir)
                await db.commit()
                if count:
                    log.info("Purged %d expired trash entries", count)
        except Exception:
            log.exception("Trash purge failed")
        await asyncio.sleep(PURGE_INTERVAL_S)


def _error_body(exc: AppError) -> dict:
    body: dict = {"error": exc.code, "message": exc.message}
    if isinstance(exc, ValidationFailed):
        body["fields"] = exc.fields
    return body


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(_purge_loop(app))]
        yield
        for task in tasks:
            task.cancel()
        await app.state.engine.dispose()

    app = FastAPI(
        title="Pick2LIGHT-Inventory",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.recent_unknown = deque(maxlen=50)
    app.state.maintenance = False

    @app.middleware("http")
    async def _same_origin_writes(request: Request, call_next):
        """Block cross-site form posts (matters most when the login is switched off)."""
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            fetch_site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            foreign_origin = origin not in (None, "null") and urlsplit(origin).netloc != request.headers.get(
                "host"
            )
            if fetch_site in ("cross-site", "same-site") or foreign_origin:
                return JSONResponse(
                    {"error": "forbidden", "message": "Requests from other websites are not allowed"},
                    status_code=403,
                )
        return await call_next(request)

    @app.middleware("http")
    async def _maintenance(request: Request, call_next):
        if app.state.maintenance and request.url.path != "/api/v1/health":
            return JSONResponse(
                {"error": "maintenance", "message": "Restoring a backup — try again in a moment"},
                status_code=503,
            )
        return await call_next(request)

    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_error_body(exc), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in err["loc"][1:]) or "body": err["msg"] for err in exc.errors()}
        return JSONResponse(
            {"error": "validation", "message": "Validation failed", "fields": fields}, status_code=422
        )

    from pick2light.api import api_router

    app.include_router(api_router, prefix="/api/v1")
    if settings.web_dist is not None and (settings.web_dist / "index.html").exists():
        _mount_web(app, settings.web_dist)
    return app


def _mount_web(app: FastAPI, dist: Path) -> None:
    """Serve the built web app; unknown non-API paths get index.html so client-side routes work."""
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise NotFound(f"No API route /{path}")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
