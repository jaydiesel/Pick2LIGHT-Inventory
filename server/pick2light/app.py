import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pick2light import __version__
from pick2light.config import Settings, get_settings
from pick2light.db import make_engine, make_sessionmaker
from pick2light.errors import AppError, ValidationFailed

log = logging.getLogger("pick2light")
PURGE_INTERVAL_S = 24 * 3600


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
    return app
