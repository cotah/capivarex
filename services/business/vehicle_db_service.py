"""
Vehicle Database Service - Refactored.

Handles storage and retrieval of vehicle tokens in Supabase.
Fully standalone implementation extending BaseService -- no imports from services/.
"""

import os
import time
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from supabase import create_client, Client

from services.core import (
    BaseService,
    ServiceConfigurationError,
    ServiceError,
    register_service,
    retry_on_failure,
)


logger = logging.getLogger("capivarex.services.vehicle_db")

# ---------------------------------------------------------------------------
# Token encryption helpers (SECURITY: encrypt OAuth tokens at rest)
# ---------------------------------------------------------------------------

_encryption_svc = None


def _get_encryptor():
    """Lazy-load EncryptionService (avoid import at module level)."""
    global _encryption_svc
    if _encryption_svc is None:
        try:
            from utils.encryption import EncryptionService
            _encryption_svc = EncryptionService()
        except Exception as exc:
            logger.warning("EncryptionService unavailable, tokens stored as plaintext: %s", exc)
            return None
    return _encryption_svc


def _encrypt_token(token: str) -> str:
    """Encrypt a token for storage. Returns plaintext if encryption unavailable."""
    enc = _get_encryptor()
    if enc:
        try:
            return enc.cipher.encrypt(token.encode()).decode()
        except Exception:
            pass
    return token


def _decrypt_token(token: str) -> str:
    """Decrypt a token from storage. Falls back to plaintext for legacy data."""
    enc = _get_encryptor()
    if enc:
        try:
            return enc.cipher.decrypt(token.encode()).decode()
        except Exception:
            # Legacy plaintext token — return as-is
            return token
    return token

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TABLE_NAME = "user_vehicles"
UPSERT_CONFLICT_COLUMNS = "user_id,vehicle_id"


@register_service("vehicle_db")
class VehicleDbService(BaseService):
    """
    Service for managing vehicle tokens in Supabase.

    Provides CRUD operations for the ``user_vehicles`` table including
    token persistence, refresh, expiration checking, and sync tracking.
    """

    def __init__(
        self,
        name: str = "vehicle_db",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the vehicle database service."""
        super().__init__(name, config)
        self._client: Optional[Client] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """
        Initialize the Supabase client using environment variables.

        Raises:
            ServiceConfigurationError: If required env vars are missing.
        """
        supabase_url: Optional[str] = self.config.get("supabase_url") or os.getenv(
            "SUPABASE_URL"
        )
        supabase_key: Optional[str] = self.config.get(
            "supabase_service_key"
        ) or os.getenv("SUPABASE_SERVICE_KEY")

        if not supabase_url or not supabase_key:
            raise ServiceConfigurationError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set "
                "(via environment or service config)"
            )

        try:
            self._client = create_client(supabase_url, supabase_key)
            self.logger.info("Supabase client created successfully")
        except Exception as exc:
            raise ServiceConfigurationError(
                f"Failed to create Supabase client: {exc}"
            ) from exc

    async def _health_check(self) -> bool:
        """
        Verify the Supabase connection by running a lightweight query.

        Returns:
            ``True`` if the query succeeds, ``False`` otherwise.
        """
        if self._client is None:
            return False
        try:
            response = (
                self._client.table(TABLE_NAME).select("vehicle_id").limit(1).execute()
            )
            # A successful response (even with empty data) means healthy.
            return response is not None
        except Exception as exc:
            self.logger.warning(f"Health check query failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Client:
        """Return the Supabase client, raising if not initialised."""
        if self._client is None:
            raise ServiceError(
                "VehicleDbService has not been initialized. Call initialize() first."
            )
        return self._client

    @staticmethod
    def _utcnow() -> datetime:
        """Return the current UTC time as a timezone-aware datetime."""
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def save_vehicle(
        self,
        user_id: str,
        vehicle_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        vehicle_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save or update a vehicle connection in the database.

        Uses an upsert on ``(user_id, vehicle_id)`` so that existing rows
        are updated transparently.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.
            access_token: Smartcar access token.
            refresh_token: Smartcar refresh token.
            expires_in: Seconds until the token expires.
            vehicle_info: Optional dict with ``make``, ``model``, ``year``,
                ``vin``.

        Returns:
            Dictionary with the saved vehicle data, or an error dict.
        """
        client = self._ensure_client()
        start = time.monotonic()

        expires_at = self._utcnow() + timedelta(seconds=expires_in)

        vehicle_data: Dict[str, Any] = {
            "user_id": user_id,
            "vehicle_id": vehicle_id,
            "access_token": _encrypt_token(access_token),
            "refresh_token": _encrypt_token(refresh_token),
            "expires_at": expires_at.isoformat(),
            "token_type": "Bearer",
        }

        if vehicle_info:
            vehicle_data.update(
                {
                    "make": vehicle_info.get("make"),
                    "model": vehicle_info.get("model"),
                    "year": vehicle_info.get("year"),
                    "vin": vehicle_info.get("vin"),
                }
            )

        try:
            response = (
                client.table(TABLE_NAME)
                .upsert(vehicle_data, on_conflict=UPSERT_CONFLICT_COLUMNS)
                .execute()
            )
            self._track_call(time.monotonic() - start)
            self.logger.debug("Vehicle saved: user=%s vehicle=%s", user_id, vehicle_id)
            return response.data[0] if response.data else {}
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error saving vehicle: %s", exc, exc_info=True)
            return {"error": str(exc)}

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def get_user_vehicles(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all vehicles for a user.

        Args:
            user_id: User UUID.

        Returns:
            List of vehicle dictionaries (empty list on error).
        """
        client = self._ensure_client()
        start = time.monotonic()

        try:
            response = (
                client.table(TABLE_NAME).select("*").eq("user_id", user_id).execute()
            )
            self._track_call(time.monotonic() - start)
            vehicles = response.data if response.data else []
            # SECURITY: Decrypt tokens that were encrypted at rest
            for v in vehicles:
                if "access_token" in v:
                    v["access_token"] = _decrypt_token(v["access_token"])
                if "refresh_token" in v:
                    v["refresh_token"] = _decrypt_token(v["refresh_token"])
            return vehicles
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error getting user vehicles: %s", exc, exc_info=True)
            return []

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def get_vehicle(
        self, user_id: str, vehicle_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific vehicle for a user.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.

        Returns:
            Vehicle dictionary, or ``None`` if not found / on error.
        """
        client = self._ensure_client()
        start = time.monotonic()

        try:
            response = (
                client.table(TABLE_NAME)
                .select("*")
                .eq("user_id", user_id)
                .eq("vehicle_id", vehicle_id)
                .execute()
            )
            self._track_call(time.monotonic() - start)
            vehicle = response.data[0] if response.data else None
            if vehicle:
                if "access_token" in vehicle:
                    vehicle["access_token"] = _decrypt_token(vehicle["access_token"])
                if "refresh_token" in vehicle:
                    vehicle["refresh_token"] = _decrypt_token(vehicle["refresh_token"])
            return vehicle
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error getting vehicle: %s", exc, exc_info=True)
            return None

    async def get_primary_vehicle(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the user's primary (first) vehicle.

        Args:
            user_id: User UUID.

        Returns:
            Vehicle dictionary, or ``None`` if the user has no vehicles.
        """
        vehicles = await self.get_user_vehicles(user_id)
        return vehicles[0] if vehicles else None

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def update_tokens(
        self,
        user_id: str,
        vehicle_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> Dict[str, Any]:
        """
        Update vehicle tokens after a token refresh.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.
            access_token: New access token.
            refresh_token: New refresh token.
            expires_in: Seconds until the new token expires.

        Returns:
            Updated vehicle data dict, or an error dict.
        """
        client = self._ensure_client()
        start = time.monotonic()

        expires_at = self._utcnow() + timedelta(seconds=expires_in)

        try:
            response = (
                client.table(TABLE_NAME)
                .update(
                    {
                        "access_token": _encrypt_token(access_token),
                        "refresh_token": _encrypt_token(refresh_token),
                        "expires_at": expires_at.isoformat(),
                    }
                )
                .eq("user_id", user_id)
                .eq("vehicle_id", vehicle_id)
                .execute()
            )
            self._track_call(time.monotonic() - start)
            self.logger.debug("Tokens updated: user=%s vehicle=%s", user_id, vehicle_id)
            return response.data[0] if response.data else {}
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error updating tokens: %s", exc, exc_info=True)
            return {"error": str(exc)}

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def delete_vehicle(self, user_id: str, vehicle_id: str) -> bool:
        """
        Delete a vehicle connection.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.

        Returns:
            ``True`` if deleted successfully, ``False`` on error.
        """
        client = self._ensure_client()
        start = time.monotonic()

        try:
            client.table(TABLE_NAME).delete().eq("user_id", user_id).eq(
                "vehicle_id", vehicle_id
            ).execute()
            self._track_call(time.monotonic() - start)
            self.logger.info("Vehicle deleted: user=%s vehicle=%s", user_id, vehicle_id)
            return True
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error deleting vehicle: %s", exc, exc_info=True)
            return False

    async def is_token_expired(self, user_id: str, vehicle_id: str) -> bool:
        """
        Check whether the vehicle token has expired.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.

        Returns:
            ``True`` if the token is expired or the vehicle is not found.
        """
        vehicle = await self.get_vehicle(user_id, vehicle_id)
        if not vehicle:
            return True

        try:
            raw_expires = vehicle["expires_at"]
            # Handle Supabase ISO strings that may end with 'Z'
            expires_at = datetime.fromisoformat(raw_expires.replace("Z", "+00:00"))
            return self._utcnow() >= expires_at
        except (KeyError, ValueError, TypeError) as exc:
            self.logger.warning(
                "Could not parse expires_at for vehicle %s: %s",
                vehicle_id,
                exc,
            )
            return True

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def update_last_synced(self, user_id: str, vehicle_id: str) -> None:
        """
        Update the ``last_synced_at`` timestamp for a vehicle.

        Args:
            user_id: User UUID.
            vehicle_id: Smartcar vehicle ID.
        """
        client = self._ensure_client()
        start = time.monotonic()

        try:
            client.table(TABLE_NAME).update(
                {"last_synced_at": self._utcnow().isoformat()}
            ).eq("user_id", user_id).eq("vehicle_id", vehicle_id).execute()
            self._track_call(time.monotonic() - start)
            self.logger.debug(
                "last_synced_at updated: user=%s vehicle=%s",
                user_id,
                vehicle_id,
            )
        except Exception as exc:
            self._track_call(time.monotonic() - start, error=True)
            self.logger.error("Error updating last_synced: %s", exc, exc_info=True)
