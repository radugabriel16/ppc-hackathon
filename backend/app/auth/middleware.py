"""Same-origin mutations and double-submit CSRF validation."""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.auth.dependencies import SAFE_METHODS
from app.alerts.router import WEBHOOK_PATH
from app.auth.security import CSRF_COOKIE_NAME, tokens_match
from app.core.errors import _error_body
from app.core.settings import get_settings


async def csrf_origin_middleware(request: Request, call_next):
    if (
        request.url.path.startswith("/api/v1/")
        and request.url.path != WEBHOOK_PATH
        and request.method not in SAFE_METHODS
    ):
        origin = request.headers.get("Origin")
        if origin != str(get_settings().app_origin).rstrip("/"):
            return JSONResponse(
                status_code=403,
                content=_error_body("ORIGIN_REJECTED", "A trusted Origin is required"),
            )
        if request.url.path != "/api/v1/auth/login":
            header = request.headers.get("X-CSRF-Token", "")
            cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
            if not header or not cookie or not tokens_match(header, cookie):
                return JSONResponse(
                    status_code=403,
                    content=_error_body("CSRF_REJECTED", "Invalid CSRF token"),
                )
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/auth/"):
        response.headers["Cache-Control"] = "no-store"
    return response
