"""
Spotify OAuth2 — Authorization Code Flow.

Flow:
1. User clica "conectar spotify" no Telegram
2. Bot envia link: /api/auth/spotify/connect?user_id=xxx
3. User autoriza no Spotify
4. Callback salva tokens no Supabase (user_oauth_tokens, provider='spotify')
5. Tokens auto-refresh via refresh_token
"""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from loguru import logger

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Scopes needed for playback control + playlist management
SPOTIFY_SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "playlist-read-private "
    "playlist-modify-public "
    "playlist-modify-private "
    "user-library-read "
    "user-library-modify "
    "user-read-recently-played"
)


class SpotifyOAuth:
    """Spotify OAuth2 service for user-level access."""

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "SPOTIFY_REDIRECT_URI",
            "https://YOUR_DOMAIN/api/auth/spotify/callback",
        )

    @property
    def is_configured(self) -> bool:
        """Check if Spotify OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def get_auth_url(self, user_id: str) -> str:
        """Generate Spotify authorization URL."""
        state = base64.urlsafe_b64encode(
            json.dumps({"user_id": user_id}).encode()
        ).decode()

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SPOTIFY_SCOPES,
            "state": state,
            "show_dialog": "true",
        }
        query = urlencode(params)
        return f"{SPOTIFY_AUTH_URL}?{query}"

    async def handle_callback(
        self, code: str, state_b64: str
    ) -> Dict[str, Any]:
        """Exchange authorization code for tokens and save to Supabase."""
        # Decode state (undo possible double URL-encoding from redirect)
        from urllib.parse import unquote

        from utils.identity import resolve_user_uuid

        state_clean = unquote(state_b64)
        padding = 4 - len(state_clean) % 4
        if padding != 4:
            state_clean += "=" * padding
        state = json.loads(base64.urlsafe_b64decode(state_clean))
        user_id = str(state["user_id"])
        user_id = await resolve_user_uuid(
            user_id, context="spotify_callback"
        )

        # Exchange code for tokens
        logger.debug(
            f"Spotify token exchange: redirect_uri={self.redirect_uri}"
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={
                    "Authorization": "Basic "
                    + base64.b64encode(
                        f"{self.client_id}:{self.client_secret}".encode()
                    ).decode(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if not response.is_success:
                logger.error(
                    f"Spotify token exchange failed:"
                    f" {response.status_code} — {response.text}"
                )
            response.raise_for_status()
            data = response.json()

        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        expires_in = data.get("expires_in", 3600)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

        # Get user profile
        async with httpx.AsyncClient() as client:
            profile = await client.get(
                f"{SPOTIFY_API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_data = profile.json()

        display_name = profile_data.get("display_name", "")
        email = profile_data.get("email", "")

        # Save to Supabase (same table as Google OAuth)
        await self._save_tokens(
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            extra_data={
                "display_name": display_name,
                "spotify_id": profile_data.get("id", ""),
            },
        )

        logger.info(
            "Spotify OAuth success: user=%s spotify=%s",
            user_id,
            display_name,
        )

        return {
            "user_id": user_id,
            "display_name": display_name,
            "email": email,
        }

    async def get_valid_token(self, user_id: str) -> Optional[str]:
        """Get valid access token, refreshing if needed."""
        token_row = await self._get_token_row(user_id)
        if not token_row:
            return None

        access_token = token_row["access_token"]
        refresh_token = token_row.get("refresh_token", "")
        expires_at_str = token_row.get("expires_at", "")

        # Check if expired (with 5 min margin)
        if expires_at_str:
            try:
                exp = datetime.fromisoformat(
                    expires_at_str.replace("Z", "+00:00")
                )
                margin = datetime.now(timezone.utc) + timedelta(minutes=5)
                if margin >= exp:
                    if not refresh_token:
                        logger.warning(
                            "Spotify token expired, no refresh_token: user=%s",
                            user_id,
                        )
                        return None
                    new_token = await self._refresh_token(
                        user_id, refresh_token
                    )
                    return new_token
            except (ValueError, TypeError):
                pass

        return access_token

    async def is_connected(self, user_id: str) -> bool:
        """Check if user has Spotify connected."""
        token = await self.get_valid_token(user_id)
        return token is not None

    async def disconnect(self, user_id: str) -> bool:
        """Disconnect Spotify (deactivate tokens in DB)."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return False
        try:
            sb.table("user_oauth_tokens").update(
                {"active": False}
            ).eq("user_id", user_id).eq(
                "provider", "spotify"
            ).execute()
            logger.info("Spotify disconnected: user=%s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to disconnect Spotify: %s", e)
            return False

    # ── Private Helpers ─────────────────────────────────────────────────────

    async def _save_tokens(
        self,
        user_id: str,
        email: str,
        access_token: str,
        refresh_token: str,
        expires_at: str,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save/update Spotify OAuth tokens in Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            raise RuntimeError("Supabase client not available")

        row = {
            "user_id": user_id,
            "provider": "spotify",
            "email": email,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "active": True,
        }
        if extra_data:
            row["extra_data"] = json.dumps(extra_data)

        sb.table("user_oauth_tokens").upsert(
            row,
            on_conflict="user_id,provider,email",
        ).execute()

    async def _get_token_row(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch Spotify token row from Supabase."""
        from services.infrastructure.database import get_supabase_client

        sb = get_supabase_client()
        if not sb:
            return None
        try:
            res = (
                sb.table("user_oauth_tokens")
                .select("*")
                .eq("user_id", user_id)
                .eq("provider", "spotify")
                .eq("active", True)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error("Failed to get Spotify OAuth tokens: %s", e)
            return None

    async def _refresh_token(
        self, user_id: str, refresh_token: str
    ) -> Optional[str]:
        """Refresh access token using refresh_token."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    SPOTIFY_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers={
                        "Authorization": "Basic "
                        + base64.b64encode(
                            f"{self.client_id}:{self.client_secret}".encode()
                        ).decode(),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                if not response.is_success:
                    logger.error(
                        f"Spotify token refresh failed:"
                        f" {response.status_code} — {response.text}"
                    )
                response.raise_for_status()
                data = response.json()

            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", refresh_token)
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=data.get("expires_in", 3600))
            ).isoformat()

            # Get existing email from token row
            token_row = await self._get_token_row(user_id)
            email = token_row.get("email", "") if token_row else ""

            await self._save_tokens(
                user_id=user_id,
                email=email,
                access_token=new_access,
                refresh_token=new_refresh,
                expires_at=expires_at,
            )

            logger.info("Spotify token refreshed for user %s", user_id)
            return new_access

        except Exception as e:
            logger.error("Spotify token refresh failed: %s", e)
            return None


# ── Singleton ────────────────────────────────────────────────────────────────

_spotify_oauth: Optional[SpotifyOAuth] = None


def get_spotify_oauth() -> SpotifyOAuth:
    """Return singleton SpotifyOAuth instance."""
    global _spotify_oauth
    if _spotify_oauth is None:
        _spotify_oauth = SpotifyOAuth()
    return _spotify_oauth
