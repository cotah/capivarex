"""
SmartThings API Routes - Refactored to use services.

OAuth 2.0 flow and device control endpoints using the SmartThings service
and database service from the service registry.

Endpoints:
    GET  /connect   - Initiate OAuth 2.0 flow for SmartThings
    GET  /callback  - OAuth 2.0 callback handler
    POST /refresh   - Refresh SmartThings OAuth tokens
    GET  /devices   - Get all SmartThings devices for a user
    POST /command   - Execute a command on a SmartThings device
    GET  /status    - Check if user has SmartThings connected
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from services.core import get_service
from api.dependencies import get_current_user
from utils.encryption import decrypt_token, encrypt_token

router = APIRouter()
logger = logging.getLogger("capivarax.api.routes.smartthings")

# OAuth Configuration
CLIENT_ID = os.getenv("SMARTTHINGS_CLIENT_ID")
CLIENT_SECRET = os.getenv("SMARTTHINGS_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SMARTTHINGS_REDIRECT_URI")

OAUTH_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_oauth_config() -> None:
    """Ensure SmartThings OAuth configuration exists."""
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail=(
                "SmartThings OAuth config missing "
                "(CLIENT_ID/SECRET/REDIRECT_URI)"
            ),
        )


def _get_smartthings_service():
    """Retrieve the SmartThings service from the registry."""
    service = get_service("smartthings")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="SmartThings service is not available",
        )
    return service


def _get_database_service():
    """Retrieve the database service from the registry."""
    service = get_service("database")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Database service is not available",
        )
    return service


def _get_supabase_client():
    """Get the raw Supabase client from the database service."""
    db_service = _get_database_service()
    return db_service.get_client()


def _parse_expires_at(raw_value: str) -> datetime:
    """Parse ISO timestamp from database."""
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).replace(
        tzinfo=None
    )


def _is_token_expired(raw_expires_at: str) -> bool:
    """Check if token expiration is in the past."""
    try:
        return _parse_expires_at(raw_expires_at) <= datetime.now()
    except Exception:
        return True


def _get_token_row(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve SmartThings token row by user_id."""
    supabase = _get_supabase_client()
    result = (
        supabase.table("smartthings_tokens")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return result.data if result and result.data else None


async def _refresh_user_tokens(user_id: str) -> Dict[str, Any]:
    """
    Refresh user tokens using refresh_token grant and persist encrypted values.

    Returns:
        Dict containing decrypted access token and updated row.
    """
    _assert_oauth_config()

    row = _get_token_row(user_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="SmartThings not connected",
        )

    encrypted_refresh = row.get("refresh_token")
    if not encrypted_refresh:
        raise HTTPException(status_code=400, detail="Missing refresh token")

    refresh_token = decrypt_token(encrypted_refresh)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        ) as response:
            response.raise_for_status()
            token_data = await response.json()

    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token", refresh_token)
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    supabase = _get_supabase_client()
    supabase.table("smartthings_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt_token(access_token),
            "refresh_token": encrypt_token(new_refresh_token),
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
    ).execute()

    logger.info("SmartThings token refreshed for user %s", user_id)
    return {"access_token": access_token, "expires_at": expires_at.isoformat()}


async def _get_valid_access_token(user_id: str) -> str:
    """
    Return a valid decrypted access token for the user.

    Refreshes token when expired.
    """
    row = _get_token_row(user_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="SmartThings not connected",
        )

    if _is_token_expired(row.get("expires_at", "")):
        refreshed = await _refresh_user_tokens(user_id)
        return refreshed["access_token"]

    return decrypt_token(row["access_token"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/connect")
async def connect_smartthings(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> RedirectResponse:
    """
    Initiate OAuth 2.0 flow for SmartThings.

    Args:
        current_user: Current authenticated user.

    Returns:
        Redirect to SmartThings authorization page.
    """
    try:
        _assert_oauth_config()

        user_id = str(current_user["id"])

        auth_url = (
            f"{OAUTH_AUTHORIZE_URL}"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=r:devices:* x:devices:*"
            f"&state={user_id}"
        )

        logger.info("User %s initiating SmartThings OAuth", user_id)
        return RedirectResponse(url=auth_url)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to initiate OAuth: %s", exc)
        raise HTTPException(status_code=500, detail="OAuth initiation failed")


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),  # user_id
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> RedirectResponse:
    """
    OAuth 2.0 callback handler.

    Exchanges authorization code for access token and stores encrypted.

    Args:
        code: Authorization code from SmartThings.
        state: User ID passed in authorization request.
        current_user: Current authenticated user.

    Returns:
        Success message with redirect.
    """
    try:
        _assert_oauth_config()
        user_id = str(current_user["id"])
        if state != user_id:
            raise HTTPException(
                status_code=403,
                detail="OAuth state mismatch for current user",
            )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                    "code": code,
                },
            ) as response:
                response.raise_for_status()
                token_data = await response.json()

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in", 3600))
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        encrypted_access = encrypt_token(access_token)
        encrypted_refresh = encrypt_token(refresh_token)

        supabase = _get_supabase_client()
        supabase.table("smartthings_tokens").upsert(
            {
                "user_id": user_id,
                "access_token": encrypted_access,
                "refresh_token": encrypted_refresh,
                "expires_at": expires_at.isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        ).execute()

        logger.info("SmartThings tokens stored for user %s", user_id)
        return RedirectResponse(url=f"/smartthings/success?user_id={user_id}")

    except HTTPException:
        raise
    except aiohttp.ClientError as exc:
        logger.error("OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=400, detail="Token exchange failed")
    except Exception as exc:
        logger.error("OAuth callback error: %s", exc)
        raise HTTPException(status_code=500, detail="OAuth callback failed")


@router.post("/refresh")
async def refresh_tokens(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Refresh SmartThings OAuth tokens for a user.

    Args:
        current_user: Current authenticated user.

    Returns:
        Refresh operation status.
    """
    try:
        user_id = str(current_user["id"])
        refreshed = await _refresh_user_tokens(user_id)
        return {
            "success": True,
            "expires_at": refreshed["expires_at"],
        }
    except HTTPException:
        raise
    except aiohttp.ClientError as exc:
        logger.error("Token refresh failed: %s", exc)
        raise HTTPException(status_code=400, detail="Token refresh failed")
    except Exception as exc:
        logger.error("Unexpected refresh error: %s", exc)
        raise HTTPException(status_code=500, detail="Token refresh failed")


@router.get("/devices")
async def get_user_devices(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get all SmartThings devices for a user.

    Args:
        current_user: Current authenticated user.

    Returns:
        List of devices.
    """
    try:
        user_id = str(current_user["id"])
        access_token = await _get_valid_access_token(user_id)

        smartthings_service = _get_smartthings_service()
        devices = await smartthings_service.get_devices(access_token=access_token)

        supabase = _get_supabase_client()
        for device in devices:
            capabilities: List[str] = []
            for comp in device.get("components", []):
                for cap in comp.get("capabilities", []):
                    cap_id = cap.get("id")
                    if cap_id:
                        capabilities.append(cap_id)

            supabase.table("smartthings_devices").upsert(
                {
                    "user_id": user_id,
                    "device_id": device.get("deviceId"),
                    "label": device.get("label"),
                    "device_type": device.get("deviceTypeName", "unknown"),
                    "room": device.get("roomId"),
                    "capabilities": capabilities,
                    "updated_at": datetime.now().isoformat(),
                }
            ).execute()

        logger.info("Retrieved %d devices for user %s", len(devices), user_id)
        return {"devices": devices}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get devices: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve devices",
        )


@router.post("/command")
async def execute_device_command(
    device_id: str,
    capability: str,
    command: str,
    arguments: Optional[List[Any]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Execute a command on a SmartThings device.

    Args:
        device_id: Device identifier.
        capability: Capability namespace.
        command: Command name.
        arguments: Optional command arguments.
        current_user: Current authenticated user.

    Returns:
        Success status.
    """
    try:
        user_id = str(current_user["id"])
        access_token = await _get_valid_access_token(user_id)

        smartthings_service = _get_smartthings_service()
        success = await smartthings_service.execute_command(
            device_id=device_id,
            capability=capability,
            command=command,
            arguments=arguments or [],
            access_token=access_token,
        )

        if success:
            logger.info(
                "Command executed: %s -> %s.%s",
                device_id,
                capability,
                command,
            )
            return {"success": True, "message": "Command executed"}

        raise HTTPException(status_code=500, detail="Command execution failed")

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to execute command: %s", exc)
        raise HTTPException(status_code=500, detail="Command execution failed")


@router.get("/status")
async def get_connection_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Check if user has SmartThings connected.

    Args:
        current_user: Current authenticated user.

    Returns:
        Connection status.
    """
    try:
        user_id = str(current_user["id"])
        supabase = _get_supabase_client()
        result = (
            supabase.table("smartthings_tokens")
            .select("expires_at")
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        if not result.data:
            return {"connected": False}

        expires_at = _parse_expires_at(result.data["expires_at"])
        is_expired = expires_at < datetime.now()

        return {
            "connected": True,
            "expires_at": expires_at.isoformat(),
            "is_expired": is_expired,
        }

    except Exception as exc:
        logger.error("Failed to check status: %s", exc)
        return {"connected": False}
