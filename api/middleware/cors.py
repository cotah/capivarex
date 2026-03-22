"""
CORS Middleware for CAPIVAREX Bot API.

Pure ASGI middleware — handles CORS preflight (OPTIONS) and adds
Access-Control-Allow-Origin to every response for allowed origins.

IMPORTANT: Implemented as pure ASGI (not BaseHTTPMiddleware) because
BaseHTTPMiddleware does NOT reliably intercept OPTIONS requests on
Railway's proxy infrastructure. This middleware operates at the raw
ASGI protocol level, guaranteed to run before any routing.
"""

import re
import os
from starlette.types import ASGIApp, Receive, Scope, Send

# ── Allowed origins ──────────────────────────────────────────────────

_ALLOWED_ORIGINS: set[str] = {
    "https://app.capivarex.com",
    "https://capivarex.com",
}

_frontend_url = os.getenv("FRONTEND_URL", "")
if _frontend_url:
    _ALLOWED_ORIGINS.add(_frontend_url.rstrip("/"))

_admin_url = os.getenv("ADMIN_URL", "")
if _admin_url:
    _ALLOWED_ORIGINS.add(_admin_url.rstrip("/"))

if os.getenv("ENVIRONMENT") == "development":
    _ALLOWED_ORIGINS.update({"http://localhost:3000", "http://localhost:5173"})

_VERCEL_REGEX = re.compile(r"https://.*capivarex.*\.vercel\.app")

# ── CORS response headers ───────────────────────────────────────────

_CORS_METHODS = b"GET, POST, PUT, DELETE, PATCH, OPTIONS"
_CORS_HEADERS = b"Authorization, Content-Type, Accept, Origin, X-Request-ID, X-Requested-With, Cache-Control, baggage, sentry-trace"
_CORS_MAX_AGE = b"86400"


def _is_allowed(origin: str) -> bool:
    if not origin:
        return False
    if origin in _ALLOWED_ORIGINS:
        return True
    return bool(_VERCEL_REGEX.fullmatch(origin))


class CORSMiddleware:
    """Pure ASGI CORS middleware.

    - OPTIONS preflight → returns 200 with full CORS headers (never reaches routing)
    - All other requests → adds CORS headers to the response
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract origin from request headers
        origin = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"origin":
                origin = header_value.decode("latin-1")
                break

        method = scope.get("method", "")

        # ── Handle OPTIONS preflight ─────────────────────────────────
        if method == "OPTIONS" and _is_allowed(origin):
            origin_bytes = origin.encode("latin-1")
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-origin", origin_bytes),
                    (b"access-control-allow-methods", _CORS_METHODS),
                    (b"access-control-allow-headers", _CORS_HEADERS),
                    (b"access-control-allow-credentials", b"true"),
                    (b"access-control-max-age", _CORS_MAX_AGE),
                    (b"content-length", b"0"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        # ── Normal request — add CORS headers to response ────────────
        if _is_allowed(origin):
            origin_bytes = origin.encode("latin-1")

            async def send_with_cors(message: dict) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"access-control-allow-origin", origin_bytes))
                    headers.append((b"access-control-allow-credentials", b"true"))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_cors)
        else:
            await self.app(scope, receive, send)
