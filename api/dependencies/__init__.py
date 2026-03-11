"""Dependencies for API."""
from typing import Any, Dict

from fastapi import Depends

from .auth import get_current_user, get_current_user_from_bearer, get_optional_user, get_admin_user
from utils.request_processor import RequestProcessor, get_request_processor


async def get_authenticated_processor(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> RequestProcessor:
    """
    Composed FastAPI dependency: authenticates user then runs RequestProcessor.

    Provides both authentication and the unified gateway (request_id, rate limit).
    """
    return await get_request_processor(current_user=current_user)


__all__ = [
    "get_current_user",
    "get_current_user_from_bearer",
    "get_optional_user",
    "get_admin_user",
    "get_authenticated_processor",
    "RequestProcessor",
]
