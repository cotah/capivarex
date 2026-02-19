"""
SmartThings Service - Refactored with BaseService architecture.

Smart home integration via SmartThings Cloud API.

Provides:
- OAuth 2.0 token management with expiration tracking
- Device discovery and status monitoring
- Generic command execution
- Convenience helpers: lights, locks, thermostat
- Health check endpoint
- Metrics tracking
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
)

load_dotenv()


@register_service("smartthings")
class SmartThingsService(BaseService):
    """
    SmartThings Cloud API integration service.

    Features:
    - OAuth 2.0 token management (set / refresh / expiry tracking)
    - Device discovery and status polling
    - Generic and typed command execution
    - Convenience methods for lights, locks, and thermostats
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "smartthings",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialise the SmartThings integration."""
        super().__init__(name, config)
        self.base_url: str = "https://api.smartthings.com/v1"
        self.access_token: Optional[str] = None
        self.expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # BaseService lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Load access token from config or environment."""
        self.access_token = self._get_config(
            "access_token",
            os.environ.get("SMARTTHINGS_ACCESS_TOKEN"),
        )
        expires_str = self._get_config("expires_at")
        if expires_str and isinstance(expires_str, str):
            try:
                self.expires_at = datetime.fromisoformat(expires_str)
            except ValueError:
                self.expires_at = None

        if not self.access_token:
            self.logger.warning(
                "SmartThings access token not provided; "
                "operations will fail until set_access_token() is called"
            )
        else:
            self.logger.info("SmartThings service initialized with access token")

    async def _health_check(self) -> bool:
        """
        Verify connectivity by attempting to list devices.

        Returns True if the API responds successfully.
        """
        if not self.access_token:
            return False

        try:
            devices = await self.get_devices()
            return isinstance(devices, list)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    @property
    def headers(self) -> Dict[str, str]:
        """Build HTTP request headers using the current token."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _make_headers(self, access_token: Optional[str] = None) -> Dict[str, str]:
        """
        Build HTTP request headers using the provided or stored token.

        Args:
            access_token: Optional per-call token override. Falls back to
                ``self.access_token`` when not supplied.

        Returns:
            Headers dictionary.
        """
        token = access_token or self.access_token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def set_access_token(
        self,
        access_token: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """
        Update the OAuth access token.

        Args:
            access_token: New bearer token.
            expires_at: Optional expiration datetime.
        """
        self.access_token = access_token
        self.expires_at = expires_at
        self.logger.info("SmartThings access token updated")

    def token_expiring_soon(self, within_minutes: int = 5) -> bool:
        """
        Check whether the token expires within the given window.

        Args:
            within_minutes: Lookahead window in minutes.

        Returns:
            True when token exists and will expire within the window.
        """
        if self.expires_at is None:
            return False
        window = datetime.utcnow() + timedelta(minutes=within_minutes)
        return window >= self.expires_at

    def _has_token(self) -> bool:
        """Return True if an access token is configured."""
        if not self.access_token:
            self.logger.warning(
                "SmartThings operation aborted: missing access token"
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Device discovery and status
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_devices(
        self, access_token: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all devices for the authenticated user.

        Args:
            access_token: Optional per-call token override. Falls back to
                the stored token.

        Returns:
            List of device dictionaries with full metadata.

        Raises:
            aiohttp.ClientError: On API communication failure.
        """
        token = access_token or self.access_token
        if not token:
            self.logger.warning("get_devices aborted: no access token")
            return []

        start_time = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/devices",
                    headers=self._make_headers(token),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    devices = data.get("items", [])

                    self._track_call(time.time() - start_time)
                    self.logger.info(
                        "Retrieved %d SmartThings devices", len(devices)
                    )
                    return devices

        except aiohttp.ClientError as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Failed to retrieve devices: %s", exc)
            raise
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Unexpected error retrieving devices: %s", exc)
            return []

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def get_device_status(
        self,
        device_id: str,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get current status of a specific device.

        Args:
            device_id: SmartThings device identifier.
            access_token: Optional per-call token override.

        Returns:
            Device status dictionary with component states.
        """
        token = access_token or self.access_token
        if not token:
            self.logger.warning("get_device_status aborted: no access token")
            return {}

        start_time = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/devices/{device_id}/status",
                    headers=self._make_headers(token),
                ) as response:
                    response.raise_for_status()
                    status = await response.json()

                    self._track_call(time.time() - start_time)
                    self.logger.debug("Device %s status retrieved", device_id)
                    return status

        except aiohttp.ClientError as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Failed to get device status: %s", exc)
            return {}
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Unexpected error getting device status: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def execute_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        arguments: Optional[List[Any]] = None,
        access_token: Optional[str] = None,
        component: str = "main",
    ) -> bool:
        """
        Execute a command on a device.

        Args:
            device_id: Target device identifier.
            capability: Capability namespace (e.g. ``switch``,
                ``switchLevel``).
            command: Command name (e.g. ``on``, ``off``, ``setLevel``).
            arguments: Optional command arguments.
            access_token: Optional per-call token override.
            component: Component name (default ``main``).

        Returns:
            True if the command executed successfully, False otherwise.
        """
        token = access_token or self.access_token
        if not token:
            self.logger.warning("execute_command aborted: no access token")
            return False

        start_time = time.time()
        try:
            payload = {
                "commands": [
                    {
                        "component": component,
                        "capability": capability,
                        "command": command,
                        "arguments": arguments or [],
                    }
                ]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/devices/{device_id}/commands",
                    headers=self._make_headers(token),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    self._track_call(time.time() - start_time)
                    self.logger.info(
                        "Command executed: %s -> %s.%s",
                        device_id,
                        capability,
                        command,
                    )
                    return True

        except aiohttp.ClientError as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Failed to execute command: %s", exc)
            return False
        except Exception as exc:
            self._track_call(time.time() - start_time, error=True)
            self.logger.error("Unexpected error executing command: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    async def turn_on_light(
        self,
        device_id: str,
        brightness: Optional[int] = None,
        access_token: Optional[str] = None,
    ) -> bool:
        """
        Turn on a light, optionally setting brightness.

        Args:
            device_id: Light device identifier.
            brightness: Optional brightness level (0-100).
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        success = await self.execute_command(
            device_id, "switch", "on", access_token=access_token
        )

        if success and brightness is not None:
            clamped = max(0, min(100, int(brightness)))
            await self.execute_command(
                device_id,
                "switchLevel",
                "setLevel",
                [clamped],
                access_token=access_token,
            )

        return success

    async def turn_off_light(
        self, device_id: str, access_token: Optional[str] = None
    ) -> bool:
        """
        Turn off a light.

        Args:
            device_id: Light device identifier.
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        return await self.execute_command(
            device_id, "switch", "off", access_token=access_token
        )

    async def turn_on_device(
        self, device_id: str, access_token: Optional[str] = None
    ) -> bool:
        """
        Turn on a switch device.

        Args:
            device_id: Device identifier.
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        return await self.execute_command(
            device_id, "switch", "on", access_token=access_token
        )

    async def turn_off_device(
        self, device_id: str, access_token: Optional[str] = None
    ) -> bool:
        """
        Turn off a switch device.

        Args:
            device_id: Device identifier.
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        return await self.execute_command(
            device_id, "switch", "off", access_token=access_token
        )

    async def lock_door(
        self, device_id: str, access_token: Optional[str] = None
    ) -> bool:
        """
        Lock a smart lock.

        Args:
            device_id: Lock device identifier.
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        return await self.execute_command(
            device_id, "lock", "lock", access_token=access_token
        )

    async def unlock_door(
        self, device_id: str, access_token: Optional[str] = None
    ) -> bool:
        """
        Unlock a smart lock.

        Args:
            device_id: Lock device identifier.
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        return await self.execute_command(
            device_id, "lock", "unlock", access_token=access_token
        )

    async def set_thermostat_temperature(
        self,
        device_id: str,
        temperature: float,
        unit: str = "C",
        access_token: Optional[str] = None,
    ) -> bool:
        """
        Set thermostat target temperature.

        Args:
            device_id: Thermostat device identifier.
            temperature: Target temperature value.
            unit: Temperature unit (``C`` or ``F``).
            access_token: Optional per-call token override.

        Returns:
            True if successful.
        """
        # SmartThings setpoint capabilities are commonly Fahrenheit-based
        if unit.upper() == "C":
            temperature = (temperature * 9 / 5) + 32

        return await self.execute_command(
            device_id,
            "thermostatCoolingSetpoint",
            "setCoolingSetpoint",
            [temperature],
            access_token=access_token,
        )

    # ------------------------------------------------------------------
    # Extended health check (original API compatibility)
    # ------------------------------------------------------------------

    async def health_check_detailed(self) -> Dict[str, Any]:
        """
        Return a detailed health status dictionary.

        Includes device count and token-expiration status.
        """
        try:
            devices = await self.get_devices()
            return {
                "status": "healthy",
                "devices_count": len(devices),
                "token_expiring_soon": self.token_expiring_soon(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            self.logger.error("Detailed health check failed: %s", exc)
            return {
                "status": "unhealthy",
                "error": str(exc),
                "timestamp": datetime.utcnow().isoformat(),
            }


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_smartthings_service: Optional[SmartThingsService] = None


def get_smartthings_service() -> SmartThingsService:
    """Get the global SmartThingsService instance from the registry."""
    global _smartthings_service
    if _smartthings_service is None:
        from services.core import get_service

        _smartthings_service = get_service("smartthings")
    return _smartthings_service
