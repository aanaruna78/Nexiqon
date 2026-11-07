"""Error envelope (RFC 9457 problem details) shared by all services."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
log = structlog.get_logger(__name__)


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


class NexiqonError(Exception):
    """Base for errors that map to a problem response."""

    status: int = 500
    code: str = "internal_error"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class BadRequest(NexiqonError):
    status, code, title = 400, "bad_request", "Bad request"


class Unauthorized(NexiqonError):
    status, code, title = 401, "unauthorized", "Unauthorized"


class Forbidden(NexiqonError):
    status, code, title = 403, "forbidden", "Forbidden"


class NotFound(NexiqonError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(NexiqonError):
    status, code, title = 409, "conflict", "Conflict"


def _response(request: Request, problem: Problem) -> JSONResponse:
    problem.instance = problem.instance or request.url.path
    problem.request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        problem.model_dump(exclude_none=True), status_code=problem.status, media_type=PROBLEM_JSON
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NexiqonError)
    async def _nexiqon(request: Request, exc: NexiqonError) -> JSONResponse:
        return _response(
            request, Problem(title=exc.title, status=exc.status, code=exc.code, detail=exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _response(
            request,
            Problem(title="Validation failed", status=422, code="validation_failed", errors=errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _response(
            request,
            Problem(title=str(exc.detail), status=exc.status_code, code=f"http_{exc.status_code}"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return _response(
            request, Problem(title="Internal error", status=500, code="internal_error")
        )
