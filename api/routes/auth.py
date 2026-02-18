"""
Authentication Routes - Refactored to use services.

Handles login, registration, token generation, and user retrieval
using the database service from the service registry.

Endpoints:
    POST /login    - Login with email/password, returns JWT token
    POST /register - Register a new user account
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, Optional

import bcrypt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from models.schemas import Token, TokenData, User, UserCreate
from services.core import get_service

load_dotenv()

logger = logging.getLogger("capivarax.api.routes.auth")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return an environment variable or raise RuntimeError if missing."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# Security configuration
SECRET_KEY: str = _require_env("JWT_SECRET_KEY")
ALGORITHM: str = _require_env("JWT_ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("JWT_EXPIRATION_MINUTES", "60"))

# OAuth2 scheme - tokenUrl must point to the real endpoint (with prefix)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

router = APIRouter()


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def _get_db_client():
    """
    Get the Supabase client from the database service in the registry.

    Returns:
        Supabase Client instance.

    Raises:
        HTTPException: If database service is unavailable.
    """
    db_service = get_service("database")
    if db_service is None:
        raise HTTPException(
            status_code=503,
            detail="Database service is not available",
        )
    return db_service.get_client()


# ---------------------------------------------------------------------------
# Password hashing / verification
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify that a plain-text password matches a bcrypt hash.

    Uses bcrypt directly to avoid passlib/bcrypt 4.x compatibility issues.

    Args:
        plain_password: The plain-text password to verify.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as e:
        logger.error("Error verifying password: %s", e)
        return False


def get_password_hash(password: str) -> str:
    """
    Generate a bcrypt hash from a plain-text password.

    Args:
        password: The password to hash.

    Returns:
        Bcrypt hash string.
    """
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Claims to encode in the token (must include "sub").
        expires_delta: Optional custom expiration timedelta.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt: str = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ---------------------------------------------------------------------------
# Current user dependency (for route protection)
# ---------------------------------------------------------------------------

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> Dict[str, Any]:
    """
    Validate the JWT bearer token and return the authenticated user.

    This is the route-protection dependency for auth-gated endpoints
    within the refactored API.

    Args:
        token: JWT token extracted from the Authorization header.

    Returns:
        User dict from the database.

    Raises:
        HTTPException 401: If credentials are invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception

    db = _get_db_client()
    response = db.table("users").select("*").eq("email", token_data.email).execute()
    user = response.data[0] if response.data else None
    if user is None:
        raise credentials_exception

    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Dict[str, str]:
    """
    Login endpoint with robust error handling.

    Accepts OAuth2 form data (username=email, password) and returns a JWT.

    Args:
        form_data: OAuth2 password request form.

    Returns:
        Dict with access_token and token_type.

    Raises:
        HTTPException 401: If email or password is incorrect.
        HTTPException 500: On unexpected server error.
    """
    # Validate password length (bcrypt limits to 72 bytes)
    if len(form_data.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        db = _get_db_client()

        # Look up user by email
        response = db.table("users").select("*").eq("email", form_data.username).execute()
        user = response.data[0] if response.data else None

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Verify password
        hashed_password = user.get("hashed_password", "")
        if not hashed_password or not verify_password(form_data.password, hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Successful login - generate token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user["email"]},
            expires_delta=access_token_expires,
        )
        return {"access_token": access_token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in login endpoint: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login",
        )


@router.post("/register", response_model=User)
async def register_user(user: UserCreate) -> Dict[str, Any]:
    """
    Register a new user account.

    Args:
        user: UserCreate schema with email, full_name, and password.

    Returns:
        Created user dict.

    Raises:
        HTTPException 400: If email is already registered or password too long.
        HTTPException 500: If user creation fails.
    """
    db = _get_db_client()

    # Check if user already exists
    existing = db.table("users").select("id").eq("email", user.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")

    if len(user.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot be longer than 72 characters.",
        )

    hashed_password = get_password_hash(user.password)

    new_user_data: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "email": user.email,
        "full_name": user.full_name,
        "hashed_password": hashed_password,
        "plan": "basic",
        "messages_limit": 100,
        "messages_used": 0,
        "use_own_apis": False,
    }

    created = db.table("users").insert(new_user_data).execute()
    created_user = created.data[0] if created.data else None
    if not created_user:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return created_user
