"""
Standardized API Error Handling for CAPIVAREX Bot API.

Provides a unified error response format across all endpoints:

    {
        "error": {
            "message": "...",
            "code": 400,
            "details": {...},
            "path": "/api/..."
        }
    }
"""

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Application-level error that produces a standardised JSON response."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        details: dict = None,
    ) -> None:
        """Initialise the error handler middleware."""
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle ``APIError`` exceptions with a consistent JSON envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "code": exc.status_code,
                "details": exc.details,
                "path": str(request.url),
            }
        },
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic ``RequestValidationError`` with the same envelope."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "message": "Validation error",
                "code": 422,
                "details": exc.errors(),
                "path": str(request.url),
            }
        },
    )


def setup_error_handlers(app) -> None:
    """
    Register error handlers on the FastAPI application.

    Args:
        app: FastAPI application instance.
    """
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
