"""
Security Headers Middleware for CAPIVAREX Bot API.

Adds essential HTTP security headers to every response to protect
against common web vulnerabilities including clickjacking, XSS,
MIME-type sniffing, and protocol downgrade attacks.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that injects security headers into all HTTP responses.

    Headers applied:
        - X-Content-Type-Options: nosniff
        - X-Frame-Options: DENY
        - X-XSS-Protection: 1; mode=block
        - Strict-Transport-Security: max-age=31536000; includeSubDomains
        - Content-Security-Policy: default-src 'self'
        - Referrer-Policy: strict-origin-when-cross-origin
        - Permissions-Policy: camera=(), microphone=(), geolocation=()
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Legacy XSS protection (still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Force HTTPS connections for 1 year
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Restrict resource loading to same origin
        # Note: 'unsafe-inline' added for Swagger UI compatibility
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Restrict browser features
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        return response
