"""
Microsoft OAuth2 Service — handles OAuth flow, token storage, and refresh
for Microsoft Graph API (Outlook Mail + Calendar + Teams).

Follows the same pattern as google_oauth_service.py.
Tokens stored in `user_oauth_tokens` with provider="microsoft".
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from services.core import get_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_REDIRECT_URI = os.getenv(
    "MICROSOFT_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/microsoft/callback",
)
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")

_AUTH_BASE = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0"
_AUTH_URL = f"{_AUTH_BASE}/authorize"
_TOKEN_URL = f"{_AUTH_BASE}/token"
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

MICROSOFT_SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "Mail.Read",
    "Mail.Send",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "OnlineMeetings.ReadWrite",
]

# Singleton
_instance: Optional["MicrosoftOAuthService"] = None


def get_microsoft_oauth() -> "MicrosoftOAuthService":
    global _instance
    if _instance is None:
        _instance = MicrosoftOAuthService()
    return _instance


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MicrosoftOAuthService:
    """Microsoft OAuth2 flow + token management via Graph API."""

    def __init__(self) -> None:
        self.client_id = MICROSOFT_CLIENT_ID
        self.client_secret = MICROSOFT_CLIENT_SECRET
        self.redirect_uri = MICROSOFT_REDIRECT_URI

    # ------------------------------------------------------------------
    # OAuth Flow
    # ------------------------------------------------------------------

    def get_authorization_url(self, user_id: str, extra_state: str = "") -> str:
        """Build Microsoft OAuth2 authorization URL."""
        state_data = json.dumps({"user_id": user_id, "extra": extra_state})
        state_b64 = base64.urlsafe_b64encode(state_data.encode()).decode()

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(MICROSOFT_SCOPES),
            "state": state_b64,
            "response_mode": "query",
            "prompt": "consent",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{_AUTH_URL}?{qs}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": " ".join(MICROSOFT_SCOPES),
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an expired access token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": " ".join(MICROSOFT_SCOPES),
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user profile from Microsoft Graph."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Token Storage (same table as Google: user_oauth_tokens)
    # ------------------------------------------------------------------

    async def save_tokens(
        self,
        user_id: str,
        token_data: Dict[str, Any],
        email: str = "",
    ) -> bool:
        """Save Microsoft tokens to database."""
        db = get_service("database")
        if not db or not db.is_initialized():
            logger.error("Database not available for token storage")
            return False

        try:
            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

            sb = db.get_client()

            # Deactivate previous Microsoft tokens for this user
            sb.table("user_oauth_tokens").update({"active": False}).eq(
                "user_id", user_id
            ).eq("provider", "microsoft").execute()

            # Upsert new token
            sb.table("user_oauth_tokens").upsert(
                {
                    "user_id": user_id,
                    "provider": "microsoft",
                    "email": email,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "scopes": MICROSOFT_SCOPES,
                    "active": True,
                },
                on_conflict="user_id,provider,email",
            ).execute()

            logger.info("Microsoft tokens saved for user %s (%s)", user_id[:8], email)
            return True
        except Exception as e:
            logger.error("Failed to save Microsoft tokens: %s", e)
            return False

    async def get_valid_token(self, user_id: str) -> Optional[str]:
        """Get a valid access token, refreshing if needed."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return None

        try:
            sb = db.get_client()
            result = (
                sb.table("user_oauth_tokens")
                .select("access_token, refresh_token, expires_at, email")
                .eq("user_id", user_id)
                .eq("provider", "microsoft")
                .eq("active", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if not result.data:
                return None

            row = result.data[0]
            access_token = row["access_token"]
            refresh_tok = row.get("refresh_token", "")
            expires_at_str = row.get("expires_at", "")
            email = row.get("email", "")

            # Check if token is still valid (5 min margin)
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(
                        expires_at_str.replace("Z", "+00:00")
                    )
                    if expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                        return access_token
                except (ValueError, TypeError):
                    pass

            # Token expired — refresh
            if refresh_tok:
                try:
                    new_tokens = await self.refresh_token(refresh_tok)
                    await self.save_tokens(user_id, new_tokens, email=email)
                    return new_tokens["access_token"]
                except Exception as e:
                    logger.warning(
                        "Microsoft token refresh failed for %s: %s", user_id[:8], e
                    )
                    return None

            return None
        except Exception as e:
            logger.error("Failed to get Microsoft token: %s", e)
            return None

    async def get_connected_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        """List all connected Microsoft accounts for a user."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        try:
            sb = db.get_client()
            result = (
                sb.table("user_oauth_tokens")
                .select("email, active, created_at")
                .eq("user_id", user_id)
                .eq("provider", "microsoft")
                .eq("active", True)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    async def disconnect(self, user_id: str) -> bool:
        """Soft-delete Microsoft connection."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        try:
            sb = db.get_client()
            sb.table("user_oauth_tokens").update({"active": False}).eq(
                "user_id", user_id
            ).eq("provider", "microsoft").execute()
            logger.info("Microsoft disconnected for user %s", user_id[:8])
            return True
        except Exception as e:
            logger.error("Failed to disconnect Microsoft: %s", e)
            return False

    async def is_connected(self, user_id: str) -> bool:
        """Check if user has an active Microsoft connection."""
        accounts = await self.get_connected_accounts(user_id)
        return len(accounts) > 0
