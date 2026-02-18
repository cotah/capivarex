"""
Rate Limiting Middleware for CapivaraX Bot API.

Uses slowapi to implement per-endpoint rate limiting, protecting
expensive AI service endpoints from abuse and cost overruns.
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Create limiter with IP-based key function
limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiting(app):
    """
    Configure rate limiting on the FastAPI application.

    Registers the limiter on ``app.state`` and installs the
    ``RateLimitExceeded`` exception handler.

    Args:
        app: FastAPI application instance.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
