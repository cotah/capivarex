"""
SmartThings OAuth2 Auto-Refresh Token Manager.

Handles automatic token refresh so SmartThings access tokens renew
transparently before they expire.

Flow:
1. On startup, reads tokens from env vars (SMARTTHINGS_CLIENT_ID,
   SMARTTHINGS_CLIENT_SECRET, SMARTTHINGS_ACCESS_TOKEN, SMARTTHINGS_REFRESH_TOKEN).
2. Caches access_token with its expiry timestamp.
3. Before each API call, checks if token expires within 1 hour.
4. If expiring, refreshes via POST https://api.smartthings.com/oauth/token
   using Basic Auth (client_id:client_secret base64-encoded).
5. Stores new tokens in Redis for persistence across restarts.
6. Falls back to legacy SMARTTHINGS_TOKEN env var if OAuth2 is not configured.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Redis keys
_REDIS_ACCESS_TOKEN = "smartthings:access_token"
_REDIS_REFRESH_TOKEN = "smartthings:refresh_token"
_REDIS_TOKEN_EXPIRY = "smartthings:token_expiry"

# 31 days TTL for Redis keys
_REDIS_TTL = 31 * 24 * 60 * 60

# Refresh when token expires within this many seconds (1 hour)
_REFRESH_WINDOW = 3600


class SmartThingsTokenManager:
    """Manages SmartThings OAuth2 tokens with auto-refresh."""

    def __init__(self) -> None:
        self.client_id: str = os.getenv("SMARTTHINGS_CLIENT_ID", "")
        self.client_secret: str = os.getenv("SMARTTHINGS_CLIENT_SECRET", "")
        self._access_token: str = os.getenv("SMARTTHINGS_ACCESS_TOKEN", "")
        self._refresh_token: str = os.getenv("SMARTTHINGS_REFRESH_TOKEN", "")
        self._legacy_token: str = os.getenv("SMARTTHINGS_TOKEN", "")
        # Expiry as a Unix timestamp; 0 means unknown / assume expired soon
        self._expires_at: float = 0.0
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_oauth_configured(self) -> bool:
        """Return True if OAuth2 credentials are available."""
        return bool(self.client_id and self.client_secret and self._refresh_token)

    async def get_valid_token(self) -> str:
        """
        Return a valid SmartThings access token.

        Refreshes automatically when the current token is about to expire.
        Falls back to the legacy SMARTTHINGS_TOKEN env var when OAuth2
        is not configured.
        """
        # Try to restore from Redis on first call
        if not self._initialized:
            await self._restore_from_redis()
            self._initialized = True

        # If OAuth2 is not configured, use legacy token
        if not self.is_oauth_configured():
            if self._access_token:
                return self._access_token
            if self._legacy_token:
                logger.info("Using legacy SMARTTHINGS_TOKEN (OAuth2 not configured)")
                return self._legacy_token
            logger.warning("No SmartThings token available")
            return ""

        # Check if token needs refresh (within 1-hour window)
        if self._token_expiring_soon():
            logger.info("SmartThings token expiring soon, refreshing...")
            await self._refresh_access_token()

        return self._access_token

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def _refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh_token grant.

        Uses Basic Auth with client_id:client_secret.
        """
        auth_string = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        headers = {
            "Authorization": f"Basic {auth_string}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = f"grant_type=refresh_token&refresh_token={self._refresh_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.smartthings.com/oauth/token",
                    headers=headers,
                    data=payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "SmartThings token refresh failed (%s): %s",
                            resp.status,
                            body,
                        )
                        return False

                    data = await resp.json()

            new_access = data.get("access_token", "")
            new_refresh = data.get("refresh_token", self._refresh_token)
            expires_in = int(data.get("expires_in", 86400))  # default 24h

            if not new_access:
                logger.error("SmartThings refresh response missing access_token")
                return False

            self._access_token = new_access
            self._refresh_token = new_refresh
            self._expires_at = time.time() + expires_in

            logger.info(
                "SmartThings token refreshed successfully (expires in %ds)",
                expires_in,
            )

            # Persist to Redis (fire-and-forget)
            await self._save_to_redis()
            return True

        except Exception as exc:
            logger.error("SmartThings token refresh error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Expiry check
    # ------------------------------------------------------------------

    def _token_expiring_soon(self) -> bool:
        """Return True if the token expires within the refresh window."""
        if self._expires_at == 0.0:
            # Unknown expiry — assume we should refresh
            return True
        return time.time() + _REFRESH_WINDOW >= self._expires_at

    # ------------------------------------------------------------------
    # Redis persistence
    # ------------------------------------------------------------------

    def _get_redis(self):
        """Get the Redis service, or None."""
        try:
            from services import get_service

            return get_service("redis")
        except Exception:
            return None

    async def _save_to_redis(self) -> None:
        """Persist current tokens and expiry to Redis."""
        redis = self._get_redis()
        if not redis:
            return

        try:
            if not redis.is_initialized():
                await redis.initialize()

            await redis.set(_REDIS_ACCESS_TOKEN, self._access_token, ex=_REDIS_TTL)
            await redis.set(_REDIS_REFRESH_TOKEN, self._refresh_token, ex=_REDIS_TTL)
            await redis.set(
                _REDIS_TOKEN_EXPIRY, str(self._expires_at), ex=_REDIS_TTL
            )
            logger.debug("SmartThings tokens persisted to Redis")
        except Exception as exc:
            logger.warning("Could not save SmartThings tokens to Redis: %s", exc)

    async def _restore_from_redis(self) -> None:
        """Restore tokens from Redis if they exist (and are fresher)."""
        redis = self._get_redis()
        if not redis:
            return

        try:
            if not redis.is_initialized():
                await redis.initialize()

            cached_access = await redis.get(_REDIS_ACCESS_TOKEN, parse_json=False)
            cached_refresh = await redis.get(_REDIS_REFRESH_TOKEN, parse_json=False)
            cached_expiry = await redis.get(_REDIS_TOKEN_EXPIRY, parse_json=False)

            if cached_access and cached_expiry:
                cached_exp = float(cached_expiry)
                # Use Redis tokens if they expire later than what we have
                if cached_exp > self._expires_at:
                    self._access_token = cached_access
                    if cached_refresh:
                        self._refresh_token = cached_refresh
                    self._expires_at = cached_exp
                    logger.info("Restored SmartThings tokens from Redis")
        except Exception as exc:
            logger.warning("Could not restore SmartThings tokens from Redis: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_token_manager: Optional[SmartThingsTokenManager] = None


def get_smartthings_token_manager() -> SmartThingsTokenManager:
    """Return the singleton SmartThingsTokenManager instance."""
    global _token_manager
    if _token_manager is None:
        _token_manager = SmartThingsTokenManager()
    return _token_manager
