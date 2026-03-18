"""
Car Service - Refactored with BaseService architecture.

Smartcar API integration for electric vehicle data and commands.

Provides:
- OAuth helpers: auth URL generation, code exchange, token refresh
- Vehicle discovery (list vehicle IDs)
- Vehicle data: info, battery, charge status, location, odometer
- Vehicle commands: lock, unlock, start/stop charging
- Vehicle summary (aggregated status string)
- Retry logic, metrics tracking, and health checks
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import smartcar
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()


@register_service("car")
class CarService(BaseService):
    """
    Car service for vehicle integration via Smartcar API.

    Features:
    - Smartcar OAuth flow helpers
    - Vehicle data (battery, charge status, location, odometer)
    - Lock / unlock and charge control commands
    - Comprehensive vehicle summary
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "car",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialise the Smartcar integration."""
        super().__init__(name, config)
        self.smartcar_client: Optional[smartcar.AuthClient] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.management_token: Optional[str] = None
        self.redirect_uri: Optional[str] = None

    # ------------------------------------------------------------------
    # BaseService lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Initialize Smartcar AuthClient from environment variables."""
        self.client_id = os.environ.get("SMARTCAR_CLIENT_ID")
        self.client_secret = os.environ.get("SMARTCAR_CLIENT_SECRET")
        self.management_token = os.environ.get("SMARTCAR_MANAGEMENT_TOKEN")
        self.redirect_uri = os.environ.get(
            "SMARTCAR_REDIRECT_URI",
            "http://localhost:8000/callback/smartcar",
        )

        if not self.client_id or not self.client_secret:
            raise ServiceUnavailableError(
                "SMARTCAR_CLIENT_ID and SMARTCAR_CLIENT_SECRET must be set"
            )

        self.smartcar_client = smartcar.AuthClient(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            mode="live",
        )

        self.logger.info("Smartcar client initialized successfully")

    async def _health_check(self) -> bool:
        """Check if Smartcar client is available."""
        return self.smartcar_client is not None

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def get_connect_url(
        self,
        user_id: str,
        scope: Optional[List[str]] = None,
    ) -> str:
        """
        Generate Smartcar Connect URL for user vehicle authorization.

        Args:
            user_id: Unique user identifier (passed as ``state``).
            scope: Permission scopes to request. Defaults to a broad
                set covering battery, location, odometer, charge control,
                and security.

        Returns:
            Authorization URL string.
        """
        if not self.smartcar_client:
            raise RuntimeError("Car service not initialized")

        if scope is None:
            scope = [
                "read_vehicle_info",
                "read_location",
                "read_odometer",
                "read_battery",
                "read_charge",
                "control_charge",
                "control_security",
            ]

        auth_url = self.smartcar_client.get_auth_url(
            scope=scope,
            options={"state": user_id},
        )
        return auth_url

    async def exchange_code(self, authorization_code: str) -> Dict[str, Any]:
        """
        Exchange an authorization code for access and refresh tokens.

        Args:
            authorization_code: Code received from Smartcar Connect redirect.

        Returns:
            Dict with ``access_token``, ``refresh_token``, ``expires_at``,
            and ``token_type``; or ``error`` on failure.
        """
        if not self.smartcar_client:
            raise RuntimeError("Car service not initialized")

        start_time = time.time()
        try:
            access = self.smartcar_client.exchange_code(authorization_code)

            self._track_call(time.time() - start_time)
            return {
                "access_token": access.access_token,
                "refresh_token": access.refresh_token,
                "expires_at": getattr(access, "expiration", None),
                "token_type": getattr(access, "token_type", "Bearer"),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error exchanging code: %s", exc)
            return {"error": f"Failed to exchange authorization code: {exc}"}

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired access token.

        Args:
            refresh_token: Refresh token from a previous authorization.

        Returns:
            Dict with new ``access_token``, ``refresh_token``, and
            ``expires_at``; or ``error`` on failure.
        """
        if not self.smartcar_client:
            raise RuntimeError("Car service not initialized")

        start_time = time.time()
        try:
            access = self.smartcar_client.exchange_refresh_token(refresh_token)

            self._track_call(time.time() - start_time)
            return {
                "access_token": access.access_token,
                "refresh_token": access.refresh_token,
                "expires_at": getattr(access, "expiration", None),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error refreshing token: %s", exc)
            return {"error": f"Failed to refresh token: {exc}"}

    # ------------------------------------------------------------------
    # Vehicle discovery
    # ------------------------------------------------------------------

    async def get_vehicle_ids(self, access_token: str) -> List[str]:
        """
        Get the list of vehicle IDs associated with an access token.

        Args:
            access_token: Valid Smartcar access token.

        Returns:
            List of vehicle ID strings (empty on error).
        """
        start_time = time.time()
        try:
            response = smartcar.get_vehicles(access_token)

            self._track_call(time.time() - start_time)
            return response.vehicles
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting vehicle IDs: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Vehicle data
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_vehicle_info(
        self, vehicle_id: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Get basic vehicle information.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``id``, ``make``, ``model``, ``year``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            attributes = vehicle.attributes()

            self._track_call(time.time() - start_time)
            return {
                "id": attributes.id,
                "make": attributes.make,
                "model": attributes.model,
                "year": attributes.year,
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting vehicle info: %s", exc)
            return {"error": f"Failed to get vehicle info: {exc}"}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_battery_level(
        self, vehicle_id: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Get current battery level and range.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``percentage``, ``range_km``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            battery = vehicle.battery()

            self._track_call(time.time() - start_time)
            return {
                "percentage": battery.percent_remaining,
                "range_km": battery.range,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting battery level: %s", exc)
            return {"error": f"Failed to get battery level: {exc}"}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_charge_status(
        self, vehicle_id: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Get charging status.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``is_plugged_in``, ``state``
            (CHARGING / FULLY_CHARGED / NOT_CHARGING), and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            charge = vehicle.charge()

            self._track_call(time.time() - start_time)
            return {
                "is_plugged_in": charge.is_plugged_in,
                "state": charge.state,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting charge status: %s", exc)
            return {"error": f"Failed to get charge status: {exc}"}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_location(self, vehicle_id: str, access_token: str) -> Dict[str, Any]:
        """
        Get current vehicle location.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``latitude``, ``longitude``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            location = vehicle.location()

            self._track_call(time.time() - start_time)
            return {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting location: %s", exc)
            return {"error": f"Failed to get location: {exc}"}

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_odometer(self, vehicle_id: str, access_token: str) -> Dict[str, Any]:
        """
        Get vehicle odometer reading.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``distance_km`` and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            odometer = vehicle.odometer()

            self._track_call(time.time() - start_time)
            return {
                "distance_km": odometer.distance,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error getting odometer: %s", exc)
            return {"error": f"Failed to get odometer: {exc}"}

    # ------------------------------------------------------------------
    # Vehicle commands
    # ------------------------------------------------------------------

    async def lock_vehicle(self, vehicle_id: str, access_token: str) -> Dict[str, Any]:
        """
        Lock the vehicle (counts towards monthly Smartcar command limit).

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``success``, ``message``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            vehicle.lock()

            self._track_call(time.time() - start_time)
            self.logger.info("Vehicle %s locked", vehicle_id)
            return {
                "success": True,
                "message": "Vehicle locked successfully",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error locking vehicle: %s", exc)
            return {"error": f"Failed to lock vehicle: {exc}"}

    async def unlock_vehicle(
        self, vehicle_id: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Unlock the vehicle (counts towards monthly Smartcar command limit).

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``success``, ``message``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            vehicle.unlock()

            self._track_call(time.time() - start_time)
            self.logger.info("Vehicle %s unlocked", vehicle_id)
            return {
                "success": True,
                "message": "Vehicle unlocked successfully",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error unlocking vehicle: %s", exc)
            return {"error": f"Failed to unlock vehicle: {exc}"}

    async def start_charging(
        self, vehicle_id: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Start vehicle charging (counts towards monthly Smartcar command limit).

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``success``, ``message``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            vehicle.start_charge()

            self._track_call(time.time() - start_time)
            self.logger.info("Charging started for vehicle %s", vehicle_id)
            return {
                "success": True,
                "message": "Charging started successfully",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error starting charging: %s", exc)
            return {"error": f"Failed to start charging: {exc}"}

    async def stop_charging(self, vehicle_id: str, access_token: str) -> Dict[str, Any]:
        """
        Stop vehicle charging (counts towards monthly Smartcar command limit).

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Dict with ``success``, ``message``, and ``timestamp``;
            or ``error`` on failure.
        """
        start_time = time.time()
        try:
            vehicle = smartcar.Vehicle(vehicle_id, access_token)
            vehicle.stop_charge()

            self._track_call(time.time() - start_time)
            self.logger.info("Charging stopped for vehicle %s", vehicle_id)
            return {
                "success": True,
                "message": "Charging stopped successfully",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Error stopping charging: %s", exc)
            return {"error": f"Failed to stop charging: {exc}"}

    # ------------------------------------------------------------------
    # Aggregated summary
    # ------------------------------------------------------------------

    async def get_vehicle_summary(self, vehicle_id: str, access_token: str) -> str:
        """
        Get a comprehensive, human-readable vehicle status summary.

        Aggregates info, battery, charge status, location, and odometer
        into a single formatted string.

        Args:
            vehicle_id: Smartcar vehicle ID.
            access_token: Valid Smartcar access token.

        Returns:
            Formatted summary string.
        """
        try:
            info = await self.get_vehicle_info(vehicle_id, access_token)
            battery = await self.get_battery_level(vehicle_id, access_token)
            charge_status = await self.get_charge_status(vehicle_id, access_token)
            location = await self.get_location(vehicle_id, access_token)
            odometer = await self.get_odometer(vehicle_id, access_token)

            summary = (
                f"**{info.get('year')} {info.get('make')} {info.get('model')}**\n\n"
                f"Battery: {battery.get('percentage', 'N/A')}%\n"
                f"Range: {battery.get('range_km', 'N/A')} km\n"
                f"Charging: {charge_status.get('state', 'N/A')}\n"
                f"Location: {location.get('latitude', 'N/A')}, "
                f"{location.get('longitude', 'N/A')}\n"
                f"Odometer: {odometer.get('distance_km', 'N/A')} km"
            )
            return summary

        except Exception as exc:
            self.logger.error("Error getting vehicle summary: %s", exc)
            return f"Error getting vehicle summary: {exc}"


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_car_service: Optional[CarService] = None


def get_car_service() -> CarService:
    """Get the global CarService instance from the registry."""
    global _car_service
    if _car_service is None:
        from services.core import get_service

        _car_service = get_service("car")
    return _car_service
