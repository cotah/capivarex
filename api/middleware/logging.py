"""Logging middleware."""
import logging
import time
from fastapi import Request

logger = logging.getLogger("capivarax.api")

async def logging_middleware(request: Request, call_next):
    """Log all requests with timing."""
    start_time = time.time()

    logger.info(f"{request.method} {request.url.path}")

    response = await call_next(request)

    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)")

    return response
