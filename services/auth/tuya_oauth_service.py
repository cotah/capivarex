"""
Tuya OAuth2 + Smart Home API service.

Flow:
1. User clicks "Connect Tuya" in CAPIVAREX webapp
2. Redirect to Tuya H5 authorization page
3. User logs in with Tuya Smart / Smart Life account
4. Callback receives authorization code
5. Exchange code for access_token + refresh_token via Tuya Cloud API
6. Store tokens in Supabase (user_oauth_tokens, provider='tuya')
7. Use tokens to control user's smart home devices

Tuya API requires HMAC-SHA256 signed requests with client credentials.
"""

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from loguru import logger

# Data center → API base URL mapping
TUYA_DATA_CENTERS = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

# H5 authorization page per data center
TUYA_H5_AUTH_URLS = {
    "eu": "https://app-h5.iot320.com/d/login",
    "us": "https://app-h5.iot320.com/d/login",
    "cn": "https://app-h5.iot320.com/d/login",
    "in": "https://app-h5.iot320.com/d/login",
}


class TuyaOAuth:
    """Tuya OAuth2 + Cloud API service."""

    def __init__(self):
        self.client_id = os.getenv("TUYA_CLIENT_ID", "")
        self.client_secret = os.getenv("TUYA_CLIENT_SECRET", "")
        self.data_center = os.getenv("TUYA_DATA_CENTER", "eu").lower()
        self.base_url = TUYA_DATA_CENTERS.get(self.data_center, TUYA_DATA_CENTERS["eu"])
        self.redirect_uri = os.getenv(
            "TUYA_REDIRECT_URI",
            "https://capivarex-production.up.railway.app/api/auth/tuya/callback",
        )

        # Cloud token (for server-to-server API calls, not user tokens)
        self._cloud_token: Optional[str] = None
        self._cloud_token_expires: float = 0

    # ------------------------------------------------------------------
    # HMAC-SHA256 Signing (required for ALL Tuya API calls)
    # ------------------------------------------------------------------

    def _sign_request(
        self,
        method: str,
        path: str,
        access_token: str = "",
        body: str = "",
        timestamp: str = "",
    ) -> Dict[str, str]:
        """
        Generate signed headers for a Tuya API request.

        Tuya requires: client_id + access_token + timestamp + nonce + sign
        The sign is HMAC-SHA256(client_secret, stringToSign)
        """
        if not timestamp:
            timestamp = str(int(time.time() * 1000))

        # Content hash (SHA-256 of body or empty string)
        content_hash = hashlib.sha256((body or "").encode("utf-8")).hexdigest()

        # String to sign
        string_to_sign = "\n".join([
            method.upper(),
            content_hash,
            "",  # headers to sign (empty for us)
            path,
        ])

        # Sign string = client_id + access_token + timestamp + string_to_sign
        sign_str = self.client_id + access_token + timestamp + string_to_sign

        # HMAC-SHA256
        sign = hmac.new(
            self.client_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        headers = {
            "client_id": self.client_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["access_token"] = access_token

        return headers

    # ------------------------------------------------------------------
    # Cloud Token (server-to-server, not user-specific)
    # ------------------------------------------------------------------

    async def _get_cloud_token(self) -> str:
        """Get a cloud-level access token for server API calls."""
        if self._cloud_token and time.time() < self._cloud_token_expires:
            return self._cloud_token

        path = "/v1.0/token?grant_type=1"
        headers = self._sign_request("GET", path)

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}{path}", headers=headers)
            data = resp.json()

        if not data.get("success"):
            # Clear cached token so next call retries fresh
            self._cloud_token = None
            self._cloud_token_expires = 0
            logger.error("Tuya cloud token failed: {}", data)
            raise RuntimeError(f"Tuya cloud token failed: {data.get('msg', 'unknown')}")

        result = data["result"]
        self._cloud_token = result["access_token"]
        self._cloud_token_expires = time.time() + result.get("expire_time", 7200) - 60

        logger.info("Tuya cloud token obtained (expires in {}s)", result.get("expire_time"))
        return self._cloud_token

    # ------------------------------------------------------------------
    # OAuth2 Authorization URL
    # ------------------------------------------------------------------

    def get_authorization_url(self, user_id: str) -> str:
        """
        Generate the Tuya H5 authorization URL.
        User clicks this → Tuya login page → callback with code.
        NOTE: This only works with OEM apps. For Smart Life / Tuya Smart,
        use direct_login() instead.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": user_id,
            "schema": "smartlife",
        }
        h5_base = TUYA_H5_AUTH_URLS.get(self.data_center, TUYA_H5_AUTH_URLS["eu"])
        url = f"{h5_base}?{urlencode(params)}"
        logger.info("Tuya OAuth URL generated for user={}", user_id[:8])
        return url

    # ------------------------------------------------------------------
    # Direct Login (email/password) — works with Smart Life / Tuya Smart
    # ------------------------------------------------------------------

    async def direct_login(
        self,
        user_id: str,
        username: str,
        password: str,
        country_code: str = "353",
        schema: str = "smartlife",
    ) -> Dict[str, Any]:
        """
        Authenticate user directly via Tuya API with email/password.
        Password is MD5-hashed before sending to Tuya.
        This bypasses the H5 page entirely.
        """
        import hashlib as _hashlib

        cloud_token = await self._get_cloud_token()

        # Tuya requires MD5-hashed password
        password_hash = _hashlib.md5(password.encode("utf-8")).hexdigest()

        path = "/v1.0/iot-01/associated-users/actions/authorized-login"
        body = json.dumps({
            "username": username,
            "password": password_hash,
            "country_code": country_code,
            "schema": schema,
        })
        headers = self._sign_request("POST", path, access_token=cloud_token, body=body)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}{path}", headers=headers, content=body
            )
            data = resp.json()

        if not data.get("success"):
            error_code = data.get("code", "unknown")
            error_msg = data.get("msg", "Login failed")
            logger.error("Tuya direct login failed: {} — {}", error_code, error_msg)
            raise ValueError(f"Tuya login failed: {error_msg} (code: {error_code})")

        result = data["result"]
        access_token = result["access_token"]
        refresh_token = result["refresh_token"]
        uid = result.get("uid", "")
        expires_in = result.get("expire_time", 7200)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Save tokens
        await self._save_tokens(
            user_id=user_id,
            tuya_uid=uid,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat(),
        )

        logger.info("Tuya direct login success: user={}, tuya_uid={}", user_id[:8], uid)
        return {
            "user_id": user_id,
            "tuya_uid": uid,
            "access_token": access_token,
        }

    # ------------------------------------------------------------------
    # OAuth2 Callback — Exchange code for user tokens
    # ------------------------------------------------------------------

    async def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """
        Exchange the authorization code for user access + refresh tokens.
        """
        user_id = state

        # Get cloud token first (needed for signed API call)
        cloud_token = await self._get_cloud_token()

        # Exchange code for user token
        path = f"/v1.0/token?grant_type=2&code={code}"
        headers = self._sign_request("GET", path, access_token=cloud_token)

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}{path}", headers=headers)
            data = resp.json()

        if not data.get("success"):
            error_msg = data.get("msg", "unknown error")
            logger.error("Tuya token exchange failed: {} — {}", data.get("code"), error_msg)
            raise ValueError(f"Tuya token exchange failed: {error_msg}")

        result = data["result"]
        access_token = result["access_token"]
        refresh_token = result["refresh_token"]
        uid = result.get("uid", "")
        expires_in = result.get("expire_time", 7200)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Save tokens
        await self._save_tokens(
            user_id=user_id,
            tuya_uid=uid,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat(),
        )

        logger.info("Tuya OAuth success: user={}, tuya_uid={}", user_id[:8], uid)
        return {
            "user_id": user_id,
            "tuya_uid": uid,
            "access_token": access_token,
        }

    # ------------------------------------------------------------------
    # Token Refresh
    # ------------------------------------------------------------------

    async def refresh_user_token(self, user_id: str) -> Optional[str]:
        """Refresh an expired user token."""
        row = await self._get_token_row(user_id)
        if not row:
            return None

        refresh_token = row.get("refresh_token", "")
        if not refresh_token:
            return None

        # Try refresh, retry once if cloud token was stale
        for attempt in range(2):
            try:
                cloud_token = await self._get_cloud_token()
            except RuntimeError:
                if attempt == 0:
                    # Force cloud token refresh on retry
                    self._cloud_token = None
                    self._cloud_token_expires = 0
                    continue
                return None

            path = f"/v1.0/token/{refresh_token}"
            headers = self._sign_request("GET", path, access_token=cloud_token)

            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}{path}", headers=headers)
                data = resp.json()

            if data.get("success"):
                break

            error_msg = data.get("msg", "")
            if "sign invalid" in error_msg and attempt == 0:
                # Cloud token might be stale — clear and retry
                self._cloud_token = None
                self._cloud_token_expires = 0
                logger.warning("Tuya refresh sign invalid, retrying with fresh cloud token")
                continue

            logger.error("Tuya token refresh failed for user={}: {}", user_id[:8], error_msg)
            return None

        result = data["result"]
        new_access = result["access_token"]
        new_refresh = result.get("refresh_token", refresh_token)
        expires_in = result.get("expire_time", 7200)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        await self._save_tokens(
            user_id=user_id,
            tuya_uid=row.get("extra_data", ""),
            access_token=new_access,
            refresh_token=new_refresh,
            expires_at=expires_at.isoformat(),
        )

        logger.info("Tuya token refreshed for user={}", user_id[:8])
        return new_access

    # ------------------------------------------------------------------
    # Get valid user token (auto-refresh if expired)
    # ------------------------------------------------------------------

    async def get_user_token(self, user_id: str) -> Optional[str]:
        """Get a valid access token for the user, refreshing if needed."""
        row = await self._get_token_row(user_id)
        if not row:
            return None

        expires_at = row.get("expires_at", "")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp > datetime.now(timezone.utc):
                    return row.get("access_token")
            except (ValueError, TypeError):
                pass

        # Token expired — refresh
        return await self.refresh_user_token(user_id)

    # ------------------------------------------------------------------
    # Device Control API
    # ------------------------------------------------------------------

    async def get_user_devices(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all devices for a user."""
        token = await self.get_user_token(user_id)
        if not token:
            return []

        row = await self._get_token_row(user_id)
        tuya_uid = row.get("extra_data", "") if row else ""
        if not tuya_uid:
            return []

        path = f"/v1.0/users/{tuya_uid}/devices"
        headers = self._sign_request("GET", path, access_token=token)

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}{path}", headers=headers)
            data = resp.json()

        if not data.get("success"):
            logger.warning("Tuya get devices failed: {}", data.get("msg"))
            return []

        devices = data.get("result", [])
        logger.info("Tuya: found {} devices for user={}", len(devices), user_id[:8])
        return devices

    async def get_device_status(self, user_id: str, device_id: str) -> List[Dict[str, Any]]:
        """Get current status of a device."""
        token = await self.get_user_token(user_id)
        if not token:
            return []

        path = f"/v1.0/devices/{device_id}/status"
        headers = self._sign_request("GET", path, access_token=token)

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}{path}", headers=headers)
            data = resp.json()

        if not data.get("success"):
            logger.warning("Tuya device status failed: {}", data.get("msg"))
            return []

        return data.get("result", [])

    async def send_command(
        self, user_id: str, device_id: str, commands: List[Dict[str, Any]]
    ) -> dict:
        """
        Send commands to a device.

        commands example: [{"code": "switch_led", "value": True}]

        Returns dict: {"success": bool, "error": str|None, "code": str|None}

        Strategy on "device is offline":
        1. Try with current token
        2. If offline → refresh token and retry (re-establishes cloud session)
        3. If still offline → try v2.0 API endpoint
        """
        token = await self.get_user_token(user_id)
        if not token:
            return {"success": False, "error": "no_token", "code": None}

        # Attempt 1: standard v1.0 command
        result = await self._send_command_raw(token, device_id, commands)
        if result.get("success"):
            return result

        # Attempt 2: if offline, refresh token and retry
        if result.get("error") == "device_offline":
            logger.info(
                "Tuya: device {} offline — refreshing token and retrying...",
                device_id[:8],
            )
            new_token = await self.refresh_user_token(user_id)
            if new_token and new_token != token:
                result2 = await self._send_command_raw(new_token, device_id, commands)
                if result2.get("success"):
                    return result2

                # Attempt 3: try v2.0 API (better cloud-device connectivity)
                result3 = await self._send_command_v2(new_token, device_id, commands)
                if result3.get("success"):
                    return result3

        return result

    async def _send_command_raw(
        self, token: str, device_id: str, commands: List[Dict[str, Any]]
    ) -> dict:
        """Low-level v1.0 command send."""
        path = f"/v1.0/devices/{device_id}/commands"
        body = json.dumps({"commands": commands})
        headers = self._sign_request("POST", path, access_token=token, body=body)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}{path}", headers=headers, content=body
            )
            data = resp.json()

        if not data.get("success"):
            msg = data.get("msg", "unknown error")
            error_code = str(data.get("code", ""))
            logger.warning(
                "Tuya command failed: {} (code={}) device={} cmds={}",
                msg, error_code, device_id[:8], commands,
            )
            if "offline" in msg.lower():
                return {"success": False, "error": "device_offline", "code": error_code}
            return {"success": False, "error": msg, "code": error_code}

        logger.info("Tuya command sent: device={}, commands={}", device_id[:8], commands)
        return {"success": True, "error": None, "code": None}

    async def _send_command_v2(
        self, token: str, device_id: str, commands: List[Dict[str, Any]]
    ) -> dict:
        """Try v2.0 IoT Core API — uses cloud token for better device reach."""
        try:
            cloud_token = await self._get_cloud_token()
        except Exception:
            return {"success": False, "error": "no_cloud_token", "code": None}

        path = f"/v2.0/cloud/thing/{device_id}/shadow/properties/issue"
        properties = [{"code": cmd["code"], "value": cmd["value"]} for cmd in commands]
        body = json.dumps({"properties": properties})
        headers = self._sign_request("POST", path, access_token=cloud_token, body=body)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}{path}", headers=headers, content=body
                )
                data = resp.json()

            if data.get("success"):
                logger.info("Tuya v2.0 command success: device={}", device_id[:8])
                return {"success": True, "error": None, "code": None}

            logger.warning("Tuya v2.0 also failed: {}", data.get("msg", ""))
        except Exception as e:
            logger.warning("Tuya v2.0 attempt failed: {}", e)

        return {"success": False, "error": "device_offline", "code": "v2_also_failed"}

    # ------------------------------------------------------------------
    # Connection status
    # ------------------------------------------------------------------

    async def is_connected(self, user_id: str) -> bool:
        """Check if user has active Tuya tokens."""
        row = await self._get_token_row(user_id)
        return row is not None and bool(row.get("access_token"))

    async def disconnect(self, user_id: str) -> bool:
        """Remove Tuya tokens for a user."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return False
        try:
            sb.table("user_oauth_tokens").delete().eq(
                "user_id", user_id
            ).eq("provider", "tuya").execute()
            logger.info("Tuya disconnected for user={}", user_id[:8])
            return True
        except Exception as e:
            logger.error("Tuya disconnect error: {}", e)
            return False

    # ------------------------------------------------------------------
    # Token storage (Supabase)
    # ------------------------------------------------------------------

    async def _save_tokens(
        self,
        user_id: str,
        tuya_uid: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
    ) -> None:
        """Save/update Tuya OAuth tokens in Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            raise RuntimeError("Supabase client not available")

        row = {
            "user_id": user_id,
            "provider": "tuya",
            "email": f"tuya:{tuya_uid}",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "extra_data": tuya_uid,
            "active": True,
        }

        sb.table("user_oauth_tokens").upsert(
            row,
            on_conflict="user_id,provider,email",
        ).execute()

        logger.info("Tuya tokens saved for user={}", user_id[:8])

    async def _get_token_row(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch Tuya token row from Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return None
        try:
            res = (
                sb.table("user_oauth_tokens")
                .select("*")
                .eq("user_id", user_id)
                .eq("provider", "tuya")
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error("Tuya get token error: {}", e)
            return None


# Singleton
_tuya_oauth: Optional[TuyaOAuth] = None


def get_tuya_oauth() -> TuyaOAuth:
    """Get or create the Tuya OAuth singleton."""
    global _tuya_oauth
    if _tuya_oauth is None:
        _tuya_oauth = TuyaOAuth()
    return _tuya_oauth
