"""Error handlers: consistent envelopes, no stack traces in production."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings
from app.services import ServiceError

logger = logging.getLogger(__name__)


def _validation_detail(exc: RequestValidationError) -> str:
    """Turn pydantic's error list into a readable single-line message."""
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = error.get("msg", "invalid value")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages) or "Request validation failed"


def register_error_handlers(app: FastAPI, settings: Settings) -> None:
    """Attach all exception handlers to the app."""

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": _validation_detail(exc), "type": "validation_error"},
        )

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "type": exc.error_type},
        )

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail, "type": "http_error"},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Never leak stack traces to clients in production.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        if settings.is_production:
            detail = "An unexpected error occurred."
        else:
            detail = f"An unexpected error occurred: {exc.__class__.__name__}: {exc}"
        return JSONResponse(status_code=500, content={"detail": detail, "type": "internal_error"})
