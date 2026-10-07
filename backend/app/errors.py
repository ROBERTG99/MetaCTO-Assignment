"""One error shape for every failure: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

log = logging.getLogger("distill")


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []
        self.headers = headers


def not_found(what: str, ident: int) -> AppError:
    return AppError(404, "not_found", f"{what} {ident} not found")


def error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def _field(loc: tuple[Any, ...]) -> str:
    names = [str(p) for p in loc if isinstance(p, str) and p not in ("body", "query", "path")]
    return ".".join(names) or "request"


async def _validation(_req: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [{"field": _field(tuple(e["loc"])), "issue": e["msg"]} for e in exc.errors()]
    message = "; ".join(f"{d['field']}: {d['issue']}" for d in details)
    return JSONResponse(error_body("validation_error", message, details), status_code=422)


async def _app_error(_req: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers
    )


async def _http_error(_req: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    codes = {404: "not_found", 405: "method_not_allowed"}
    return JSONResponse(
        error_body(codes.get(exc.status_code, "http_error"), str(exc.detail)),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def _unexpected(req: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", req.method, req.url.path)  # no body: it may hold user text
    return JSONResponse(error_body("internal_error", "Internal server error"), status_code=500)


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
