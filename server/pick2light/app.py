from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pick2light import __version__
from pick2light.api import api_router
from pick2light.config import Settings, get_settings
from pick2light.errors import AppError


def _error(
    status: int, code: str, message: str, fields: dict[str, str] | None = None
) -> JSONResponse:
    body: dict[str, object] = {"error": code, "message": message}
    if fields:
        body["fields"] = fields
    return JSONResponse(body, status_code=status)


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _error(exc.status_code, exc.code, exc.message, exc.fields)


async def _request_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(part) for part in err["loc"]]
        key = ".".join(loc[1:]) or ".".join(loc)
        fields.setdefault(key, err["msg"])
    return _error(422, "validation", "Validation failed", fields)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    message = str(exc.detail)
    if exc.status_code == 401:
        return _error(401, "unauthenticated", message)
    if exc.status_code == 404:
        return _error(404, "not_found", message)
    return _error(exc.status_code, "invalid_operation", message)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Pick2LIGHT-Inventory",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings or get_settings()
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.include_router(api_router, prefix="/api/v1")
    return app
