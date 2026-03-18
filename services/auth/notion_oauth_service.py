"""
Notion OAuth2 Service — handles OAuth flow, token storage, and access
for the Notion API. Users select which pages to share during consent.

Follows the same pattern as google_oauth_service.py / microsoft_oauth_service.py.
Tokens stored in `user_oauth_tokens` with provider="notion".
"""

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from services.core import get_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID", "")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET", "")
NOTION_REDIRECT_URI = os.getenv(
    "NOTION_REDIRECT_URI",
    "http://localhost:8000/api/auth/notion/callback",
)

_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
_API_BASE = "https://api.notion.com/v1"
_API_VERSION = "2022-06-28"

# Singleton
_instance: Optional["NotionOAuthService"] = None


def get_notion_oauth() -> "NotionOAuthService":
    global _instance
    if _instance is None:
        _instance = NotionOAuthService()
    return _instance


class NotionOAuthService:
    """Notion OAuth2 flow + token management."""

    def __init__(self) -> None:
        self.client_id = NOTION_CLIENT_ID
        self.client_secret = NOTION_CLIENT_SECRET
        self.redirect_uri = NOTION_REDIRECT_URI

    # ------------------------------------------------------------------
    # OAuth Flow
    # ------------------------------------------------------------------

    def get_authorization_url(self, user_id: str) -> str:
        """Build Notion OAuth2 authorization URL.

        The user will select which pages to share during consent.
        The token will only have access to those pages.
        """
        state_data = json.dumps({"user_id": user_id})
        state_b64 = base64.urlsafe_b64encode(state_data.encode()).decode()

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state_b64,
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{_AUTH_URL}?{qs}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token.

        Notion uses HTTP Basic Auth (client_id:client_secret) for token exchange.
        Returns: {access_token, workspace_id, workspace_name, bot_id, ...}
        """
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/json",
                    "Notion-Version": _API_VERSION,
                },
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Token Storage
    # ------------------------------------------------------------------

    async def save_tokens(
        self,
        user_id: str,
        token_data: Dict[str, Any],
    ) -> bool:
        """Save Notion tokens to database.

        Notion tokens don't expire (no refresh_token), but we store
        workspace_id and workspace_name as metadata.
        """
        db = get_service("database")
        if not db or not db.is_initialized():
            logger.error("Database not available for Notion token storage")
            return False

        try:
            access_token = token_data["access_token"]
            workspace_name = token_data.get("workspace_name", "")

            # Owner info (the user who authorized)
            owner = token_data.get("owner", {})
            owner_type = owner.get("type", "")
            owner_user = owner.get("user", {}) if owner_type == "user" else {}
            email = owner_user.get("person", {}).get("email", "")

            sb = db.get_client()

            # Deactivate previous Notion tokens
            sb.table("user_oauth_tokens").update({"active": False}).eq(
                "user_id", user_id
            ).eq("provider", "notion").execute()

            # Upsert new token
            sb.table("user_oauth_tokens").upsert(
                {
                    "user_id": user_id,
                    "provider": "notion",
                    "email": email or workspace_name,
                    "access_token": access_token,
                    "refresh_token": "",  # Notion tokens don't expire
                    "expires_at": None,
                    "scopes": [],
                    "active": True,
                },
                on_conflict="user_id,provider,email",
            ).execute()

            logger.info(
                "Notion tokens saved for user %s (workspace: %s)",
                user_id[:8],
                workspace_name,
            )
            return True
        except Exception as e:
            logger.error("Failed to save Notion tokens: %s", e)
            return False

    async def get_valid_token(self, user_id: str) -> Optional[str]:
        """Get the Notion access token. Notion tokens don't expire."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return None

        try:
            sb = db.get_client()
            result = (
                sb.table("user_oauth_tokens")
                .select("access_token")
                .eq("user_id", user_id)
                .eq("provider", "notion")
                .eq("active", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["access_token"]
            return None
        except Exception as e:
            logger.error("Failed to get Notion token: %s", e)
            return None

    async def is_connected(self, user_id: str) -> bool:
        """Check if user has an active Notion connection."""
        token = await self.get_valid_token(user_id)
        return token is not None

    async def get_connected_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        """List connected Notion accounts."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        try:
            sb = db.get_client()
            result = (
                sb.table("user_oauth_tokens")
                .select("email, active, created_at")
                .eq("user_id", user_id)
                .eq("provider", "notion")
                .eq("active", True)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    async def disconnect(self, user_id: str) -> bool:
        """Soft-delete Notion connection."""
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        try:
            sb = db.get_client()
            sb.table("user_oauth_tokens").update({"active": False}).eq(
                "user_id", user_id
            ).eq("provider", "notion").execute()
            logger.info("Notion disconnected for user %s", user_id[:8])
            return True
        except Exception as e:
            logger.error("Failed to disconnect Notion: %s", e)
            return False
