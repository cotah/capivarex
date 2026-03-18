"""
Spotify User Service — User-level operations requiring OAuth.

Separate from SpotifyService (Client Credentials, search-only).
This service uses the user's OAuth token for:
- Playback control (play, pause, next, previous, volume)
- Playlist management (list, create, add tracks)
- Library (liked songs, save/unsave)
- Currently playing info
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

SPOTIFY_API = "https://api.spotify.com/v1"


class SpotifyUserService:
    """User-level Spotify operations via OAuth token."""

    def __init__(self, access_token: str):
        self._token = access_token
        self._headers = {"Authorization": f"Bearer {access_token}"}

    # ── Playback Control ──────────────────────────────────

    async def play(
        self,
        uri: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> bool:
        """Start or resume playback. Optionally play a specific track/album."""
        url = f"{SPOTIFY_API}/me/player/play"
        params: Dict[str, str] = {}
        if device_id:
            params["device_id"] = device_id

        body: Dict[str, Any] = {}
        if uri:
            if "track" in uri:
                body["uris"] = [uri]
            else:
                body["context_uri"] = uri

        async with httpx.AsyncClient() as client:
            r = await client.put(
                url,
                json=body or None,
                params=params,
                headers=self._headers,
            )
            return r.status_code in (200, 204)

    async def pause(self) -> bool:
        """Pause playback."""
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{SPOTIFY_API}/me/player/pause",
                headers=self._headers,
            )
            return r.status_code in (200, 204)

    async def next_track(self) -> bool:
        """Skip to next track."""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SPOTIFY_API}/me/player/next",
                headers=self._headers,
            )
            return r.status_code in (200, 204)

    async def previous_track(self) -> bool:
        """Go to previous track."""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SPOTIFY_API}/me/player/previous",
                headers=self._headers,
            )
            return r.status_code in (200, 204)

    async def set_volume(self, volume: int) -> bool:
        """Set volume (0-100)."""
        volume = max(0, min(100, volume))
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{SPOTIFY_API}/me/player/volume",
                params={"volume_percent": volume},
                headers=self._headers,
            )
            return r.status_code in (200, 204)

    async def get_currently_playing(self) -> Optional[Dict[str, Any]]:
        """Get currently playing track info."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SPOTIFY_API}/me/player/currently-playing",
                headers=self._headers,
            )
            if r.status_code == 204:
                return None  # Nothing playing
            if r.status_code == 200:
                return r.json()
            return None

    async def get_devices(self) -> List[Dict[str, Any]]:
        """Get available playback devices."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SPOTIFY_API}/me/player/devices",
                headers=self._headers,
            )
            if r.status_code == 200:
                return r.json().get("devices", [])
            return []

    # ── Playlist Management ───────────────────────────────

    async def get_playlists(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get user's playlists."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SPOTIFY_API}/me/playlists",
                params={"limit": limit},
                headers=self._headers,
            )
            if r.status_code == 200:
                return r.json().get("items", [])
            return []

    async def add_to_playlist(self, playlist_id: str, track_uri: str) -> bool:
        """Add a track to a playlist."""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
                json={"uris": [track_uri]},
                headers=self._headers,
            )
            return r.status_code == 201

    async def save_track(self, track_id: str) -> bool:
        """Save track to user's library (like)."""
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{SPOTIFY_API}/me/tracks",
                json={"ids": [track_id]},
                headers=self._headers,
            )
            return r.status_code == 200

    async def get_recently_played(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently played tracks."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SPOTIFY_API}/me/player/recently-played",
                params={"limit": limit},
                headers=self._headers,
            )
            if r.status_code == 200:
                return r.json().get("items", [])
            return []
