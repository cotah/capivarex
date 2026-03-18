"""Autofix exception middleware for the refactored API."""

import asyncio
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from autofix import record_exception
from services.infrastructure.security_event_service import record_security_event

logger = logging.getLogger("capivarex.api.middleware.autofix")


async def autofix_exception_middleware(
    request: Request, call_next: Callable
) -> Response:
    """
    Global middleware to capture unhandled exceptions and record them
    via the autofix system.

    When a new ticket is created (is_new=True), it also triggers a Telegram
    notification to the admin so they can review and approve a patch.

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

        ticket, is_new = record_exception(
            error=e,
            chat_id="api",
            text=f"API Error on {request.method} {request.url.path}",
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # ── Telegram admin alert ──────────────────────────────────────────
        # Notify admin of new (or recurring) tickets so they can review patches
        if ticket:
            try:
                from autofix.notifier import notify_new_ticket

                asyncio.create_task(notify_new_ticket(ticket, is_new))
            except Exception:
                pass  # never block the response

        # ── Security event log ────────────────────────────────────────────
        try:
            asyncio.create_task(
                record_security_event(
                    "server_error",
                    "high",
                    user_id=user_id if user_id != "api_guest" else None,
                    ip_address=request.client.host if request.client else None,
                    endpoint=f"{request.method} {request.url.path}",
                    details={"error": type(e).__name__, "message": str(e)[:200]},
                )
            )
        except Exception:
            pass

        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred. The issue has been logged."
            },
        )
