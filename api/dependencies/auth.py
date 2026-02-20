"""
Authentication dependencies for the refactored API.

Uses services (get_service) for database access
instead of direct imports from services/.
"""
from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
import jwt
from jwt.exceptions import PyJWTError

from models.schemas import TokenData
from services.core import get_service

load_dotenv()

logger = logging.getLogger("capivarax.api.dependencies.auth")

# Security configuration
SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")

# OAuth2 scheme -- tokenUrl points at the real auth endpoint (with prefix)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# HTTPBearer for WebSocket and alternative auth
security = HTTPBearer()


def _get_db():
    """Get the Supabase client via the refactored database service."""
    db_service = get_service("database")
    if db_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable",
        )
    return db_service.get_client()


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> Dict[str, Any]:
    """
    Get current authenticated user from an OAuth2 bearer token (JWT).

    Validates the JWT, extracts the email, and looks up the user
    in the database via services.

    Args:
        token: JWT access token extracted by FastAPI's OAuth2PasswordBearer.

    Returns:
        Dict with full user row from the database.

    Raises:
        HTTPException 401: If the token is invalid or the user is not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not SECRET_KEY:
        logger.error("JWT_SECRET_KEY is not configured")
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except PyJWTError:
        raise credentials_exception

    db = _get_db()
    response = db.table("users").select("*").eq("email", token_data.email).execute()
    user = response.data[0] if response.data else None

    if user is None:
        raise credentials_exception

    return user


async def get_current_user_from_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """
    Alternative authentication via HTTPBearer (used by some endpoints).

    Extracts the raw token from the Authorization header and delegates
    to get_current_user.

    Args:
        credentials: HTTP Bearer credentials extracted by FastAPI.

    Returns:
        Dict with full user row from the database.

    Raises:
        HTTPException 401: If authentication fails.
    """
    return await get_current_user(credentials.credentials)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[Dict[str, Any]]:
    """
    Get current user if authenticated, None otherwise.

    Uses auto_error=False so that missing/invalid tokens do not raise
    an automatic 403 -- instead we simply return None.

    Args:
        credentials: Optional HTTP Bearer credentials.

    Returns:
        Dict with user information or None if not authenticated.
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials.credentials)
    except Exception as exc:
        logger.debug("Optional auth failed: %s", exc)
        return None
