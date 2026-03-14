"""
Car Routes - Refactored Electric Vehicle Management Endpoints.

Uses services (car, vehicle_db) and agents (car)
via the registry pattern with get_service() / get_agent().

Endpoints:
    POST /query          - Process user query about their vehicle
    POST /connect        - Get Smartcar Connect URL for vehicle authorization
    GET  /callback/smartcar  - OAuth callback from Smartcar
    POST /refresh        - Refresh expired access token
    GET  /battery        - Get vehicle battery level
    GET  /location       - Get vehicle location
    GET  /charge-status  - Get vehicle charging status
    GET  /summary        - Get comprehensive vehicle summary
    POST /lock           - Lock the vehicle
    POST /unlock         - Unlock the vehicle
    POST /start-charging - Start vehicle charging
    POST /stop-charging  - Stop vehicle charging
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from agents import get_agent
from api.dependencies.auth import get_current_user
from services.core import get_service
from utils.identity import resolve_user_uuid

router = APIRouter()
logger = logging.getLogger("capivarex.api.routes.car")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CarQueryRequest(BaseModel):
    """Request model for car queries."""

    message: str
    user_id: str
    vehicle_id: Optional[str] = None
    access_token: Optional[str] = None


class CarConnectRequest(BaseModel):
    """Request model for vehicle connection."""

    user_id: str


class CarCallbackRequest(BaseModel):
    """Request model for OAuth callback."""

    code: str
    state: str  # user_id


# ---------------------------------------------------------------------------
# Service / Agent helpers
# ---------------------------------------------------------------------------


async def _get_car_service_async():
    """Retrieve and initialize the car service from the registry."""
    service = get_service("car")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Car service is not available",
        )
    if not service.is_initialized():
        try:
            await service.initialize()
        except Exception as e:
            logger.error("CarService initialization failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail="Car service failed to initialize — check SMARTCAR env vars",
            )
    return service


def _get_car_service():
    """Retrieve the car service from the registry (sync, no init check)."""
    service = get_service("car")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Car service is not available",
        )
    return service


def _get_vehicle_db_service():
    """Retrieve the vehicle database service from the registry."""
    service = get_service("vehicle_db")
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Vehicle database service is not available",
        )
    return service


def _get_car_agent():
    """Retrieve the car agent from the registry."""
    agent = get_agent("car")
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Car agent is not available",
        )
    return agent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/query")
async def query_car(
    request: CarQueryRequest, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Process user query about their vehicle.

    Args:
        request: CarQueryRequest with user message and optional vehicle credentials.

    Returns:
        Response from Car Agent.
    """
    try:
        car_agent = _get_car_agent()

        response = await car_agent.process(
            user_message=request.message,
            user_id=request.user_id,
            vehicle_id=request.vehicle_id,
            access_token=request.access_token,
        )

        return {"success": True, "response": response}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing car query: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connect")
async def connect_vehicle_redirect(
    user_id: str = Query(default="unknown"),
) -> RedirectResponse:
    """
    GET /connect — redirect to Smartcar OAuth consent screen.
    Used by the frontend popup flow (window.open).
    """
    try:
        car_service = await _get_car_service_async()
        connect_url = car_service.get_connect_url(user_id)
        logger.info("User %s initiating Smartcar OAuth", user_id[:8] if len(user_id) > 8 else user_id)
        return RedirectResponse(url=connect_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating Smartcar connect URL: %s", e)
        raise HTTPException(status_code=500, detail="Smartcar OAuth initiation failed")


@router.post("/connect")
async def connect_vehicle(
    request: CarConnectRequest, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get Smartcar Connect URL for user to authorize vehicle access.

    Args:
        request: CarConnectRequest with user_id.

    Returns:
        Smartcar Connect URL.
    """
    try:
        car_service = await _get_car_service_async()
        connect_url = car_service.get_connect_url(request.user_id)

        return {
            "success": True,
            "connect_url": connect_url,
            "message": "Redirect user to this URL to connect their vehicle",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating connect URL: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback/smartcar")
async def smartcar_callback(
    code: str = Query(..., description="Authorization code from Smartcar"),
    state: str = Query(..., description="User ID passed as state parameter"),
) -> Dict[str, Any]:
    """
    OAuth callback endpoint for Smartcar.

    Receives the authorization code from Smartcar after user authorizes
    vehicle access. Exchanges code for tokens and stores them.

    Args:
        code: Authorization code from Smartcar.
        state: User ID (passed as state parameter).

    Returns:
        Access token and vehicle information.
    """
    try:
        car_service = await _get_car_service_async()
        vehicle_db = _get_vehicle_db_service()

        user_id = await resolve_user_uuid(
            state, context="smartcar_callback"
        )

        # Exchange authorization code for tokens
        tokens = await car_service.exchange_code(code)

        if "error" in tokens:
            raise HTTPException(status_code=400, detail=tokens["error"])

        # Get vehicle IDs associated with this access token
        vehicle_ids = await car_service.get_vehicle_ids(tokens["access_token"])

        if not vehicle_ids:
            raise HTTPException(status_code=400, detail="No vehicles found")

        # Get info for first vehicle (users typically have one vehicle)
        vehicle_id = vehicle_ids[0]
        vehicle_info = await car_service.get_vehicle_info(
            vehicle_id, tokens["access_token"]
        )

        # Save vehicle and tokens to database
        saved_vehicle = await vehicle_db.save_vehicle(
            user_id=user_id,
            vehicle_id=vehicle_id,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_in=tokens.get("expires_in", 7200),
            vehicle_info=vehicle_info,
        )

        if "error" in saved_vehicle:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save vehicle: {saved_vehicle['error']}",
            )

        return {
            "success": True,
            "user_id": user_id,
            "vehicle_id": vehicle_id,
            "vehicle_info": vehicle_info,
            "message": "Vehicle connected successfully! Tokens stored securely.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in Smartcar callback: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_token(
    refresh_token: str, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Refresh expired access token.

    Args:
        refresh_token: Refresh token from previous authorization.

    Returns:
        New access token.
    """
    try:
        car_service = await _get_car_service_async()
        tokens = await car_service.refresh_access_token(refresh_token)

        if "error" in tokens:
            raise HTTPException(status_code=400, detail=tokens["error"])

        return {
            "success": True,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": tokens["expires_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error refreshing token: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/battery")
async def get_battery(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get vehicle battery level."""
    try:
        car_service = await _get_car_service_async()
        battery = await car_service.get_battery_level(vehicle_id, access_token)
        return {"success": True, "data": battery}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting battery: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/location")
async def get_location(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get vehicle location."""
    try:
        car_service = await _get_car_service_async()
        location = await car_service.get_location(vehicle_id, access_token)
        return {"success": True, "data": location}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting location: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/charge-status")
async def get_charge_status(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get vehicle charging status."""
    try:
        car_service = await _get_car_service_async()
        charge_status = await car_service.get_charge_status(vehicle_id, access_token)
        return {"success": True, "data": charge_status}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting charge status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_summary(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get comprehensive vehicle summary."""
    try:
        car_service = await _get_car_service_async()
        summary = await car_service.get_vehicle_summary(vehicle_id, access_token)
        return {"success": True, "summary": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting vehicle summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lock")
async def lock_vehicle(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Lock the vehicle (COMMAND - counts towards monthly limit)."""
    try:
        car_service = await _get_car_service_async()
        result = await car_service.lock_vehicle(vehicle_id, access_token)
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error locking vehicle: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unlock")
async def unlock_vehicle(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Unlock the vehicle (COMMAND - counts towards monthly limit)."""
    try:
        car_service = await _get_car_service_async()
        result = await car_service.unlock_vehicle(vehicle_id, access_token)
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error unlocking vehicle: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start-charging")
async def start_charging(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Start vehicle charging (COMMAND - counts towards monthly limit)."""
    try:
        car_service = await _get_car_service_async()
        result = await car_service.start_charging(vehicle_id, access_token)
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error starting charging: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-charging")
async def stop_charging(
    vehicle_id: str,
    access_token: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Stop vehicle charging (COMMAND - counts towards monthly limit)."""
    try:
        car_service = await _get_car_service_async()
        result = await car_service.stop_charging(vehicle_id, access_token)
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error stopping charging: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
