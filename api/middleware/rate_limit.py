"""
Rate Limiting Middleware for CAPIVAREX Bot API.

Uses slowapi to implement per-endpoint rate limiting, protecting
expensive AI service endpoints from abuse and cost overruns.

Supports plan-based rate limit keys: authenticated users are
identified by their JWT subject + plan, allowing different rate
limits per subscription tier.
"""

import asyncio
import logging
import os

import jwt
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("capivarex.rate_limit")


def get_user_plan_key(request: Request) -> str:
    """Determine the rate limit key based on user identity and plan.

    For authenticated users the key is ``{user_id}:{plan}``, which allows
    slowapi decorators to apply different limits per plan tier.  For
    anonymous / unauthenticated requests the key falls back to the remote
    IP address with a ``default`` plan.

    Note: The JWT signature is **not** verified here — full verification
    is the responsibility of the authentication dependency on each
    endpoint.  This function only reads the ``sub`` and ``plan`` claims
    so that the limiter can build its key.
    """
    ip = get_remote_address(request)
    user_id = ip
    plan = "default"

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            _secret = os.environ.get("JWT_SECRET_KEY", "")
            _algo = os.environ.get("JWT_ALGORITHM", "HS256")
            if _secret:
                payload = jwt.decode(token, _secret, algorithms=[_algo])
            else:
                # Dev/test: still verify structure but log warning
                payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub", ip)
            plan = payload.get("plan", "default")
        except jwt.PyJWTError:
            pass

    return f"{user_id}:{plan}"


# Create limiter with plan-aware key function
limiter = Limiter(key_func=get_user_plan_key)


async def _rate_limit_with_logging(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom rate limit exceeded handler that logs a security event
    before delegating to the default slowapi handler.
    """
    try:
        from services.infrastructure.security_event_service import record_security_event
        asyncio.create_task(
            record_security_event(
                "rate_limit_exceeded",
                "medium",
                ip_address=request.client.host if request.client else None,
                endpoint=str(request.url.path),
                details={"detail": str(getattr(exc, 'detail', 'rate limit exceeded'))},
            )
        )
    except Exception:
        pass
    return _rate_limit_exceeded_handler(request, exc)


def setup_rate_limiting(app):
    """
    Configure rate limiting on the FastAPI application.

    Registers the limiter on ``app.state`` and installs the
    ``RateLimitExceeded`` exception handler with security event logging.

    Args:
        app: FastAPI application instance.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_with_logging)
