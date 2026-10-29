"""Standard error body {code, message, details} for every non-2xx response (api.md 1.1)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

CODES = {400: "validation_error", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "not_found",
         409: "conflict", 422: "validation_error", 502: "upstream_error"}


class ApiError(Exception):
    def __init__(self, status: int, message: str, details: list[dict[str, str]] | None = None, code: str | None = None):
        self.status, self.message, self.details = status, message, details
        self.code = code or CODES.get(status, "internal_error")


def body(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(body(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        code = CODES.get(exc.status_code, "internal_error")
        return JSONResponse(body(code, str(exc.detail), None), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(body("validation_error", "Request validation failed", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(body("internal_error", "Internal server error", None), status_code=500)
