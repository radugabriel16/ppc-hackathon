"""Standard `{code, message, fieldErrors, requestId}` error envelope (PHASE1.md section 5)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = logging.getLogger("app.errors")


def _error_body(code: str, message: str, field_errors: list[dict] | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "fieldErrors": field_errors or [],
        "requestId": get_request_id(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body("VALIDATION_ERROR", "Request validation failed", field_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else "HTTP_ERROR"
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        headers = exc.headers
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code or "HTTP_ERROR", message or "Request failed"),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("INTERNAL_ERROR", "An unexpected error occurred"),
        )
