"""Autofix exception middleware for the refactored API."""
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from autofix import record_exception

logger = logging.getLogger("capivarex.api.middleware.autofix")


async def autofix_exception_middleware(request: Request, call_next: Callable) -> Response:
    """
    Global middleware to capture unhandled exceptions and record them
    via the autofix system.

    Args:
        request: Incoming HTTP request.
        call_next: Next middleware/route handler.

    Returns:
        HTTP response (normal or 500 error).
    """
    try:
        response: Response = await call_next(request)
        return response
    except Exception as e:
        user_id: str = "api_guest"
        tenant_id: str = "api_default"

        if hasattr(request.state, "user") and request.state.user:
            user_id = str(request.state.user.get("id", user_id))
            tenant_id = str(request.state.user.get("tenant_id", tenant_id))

        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            e,
            exc_info=True,
        )

        record_exception(
            error=e,
            chat_id="api",
            text=f"API Error on {request.method} {request.url.path}",
            user_id=user_id,
            tenant_id=tenant_id,
        )

        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. The issue has been logged."},
        )
