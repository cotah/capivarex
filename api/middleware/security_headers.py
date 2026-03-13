"""
Security Headers Middleware for CAPIVAREX Bot API.

Adds essential HTTP security headers to every response to protect
against common web vulnerabilities including clickjacking, XSS,
MIME-type sniffing, and protocol downgrade attacks.

IMPORTANT: Implemented as a pure ASGI middleware (not BaseHTTPMiddleware)
to avoid interfering with CORSMiddleware. BaseHTTPMiddleware reconstructs
the response object, which strips CORS headers added by CORSMiddleware.
"""

from starlette.types import ASGIApp, Receive, Scope, Send, Message

# Headers to inject into every HTTP response.
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security headers into HTTP responses.

    Unlike the previous BaseHTTPMiddleware implementation, this operates
    at the ASGI protocol level and does NOT reconstruct the response,
    so headers added by outer middleware (like CORSMiddleware) are preserved.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
