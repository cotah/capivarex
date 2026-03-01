"""
services/integrations/spotify_service.py
=========================================
Spotify Web API integration service.

Uses Client Credentials flow (server-to-server auth)
for searching tracks, artists, albums, and getting
recommendations via the Spotify API.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from services.core import BaseService, register_service

logger = logging.getLogger(__name__)

# Spotify API endpoints
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


@register_service("spotify")
class SpotifyService(BaseService):
    """Spotify Web API service with auto-refreshing token."""

    def __init__(
        self,
        name: str = "spotify",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, config)
        self._client_id: str = ""
        self._client_secret: str = ""
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._http: Optional[httpx.AsyncClient] = None

    async def _initialize(self) -> None:
        self._client_id = os.getenv(
            "SPOTIFY_CLIENT_ID", ""
        )
        self._client_secret = os.getenv(
            "SPOTIFY_CLIENT_SECRET", ""
        )
        if not self._client_id or not self._client_secret:
            self.logger.warning(
                "SPOTIFY_CLIENT_ID or "
                "SPOTIFY_CLIENT_SECRET not set"
            )
            return
        self._http = httpx.AsyncClient(timeout=15.0)
        await self._refresh_token()
        self.logger.info(
            "Spotify service initialized successfully"
        )

    async def _health_check(self) -> bool:
        return bool(self._access_token)

    # ── Token Management ──────────────────────────────

    async def _refresh_token(self) -> None:
        """Get or refresh token via Client Credentials."""
        try:
            response = await self._http.post(
                SPOTIFY_AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={
                    "Content-Type": (
                        "application/x-www-form-urlencoded"
                    )
                },
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            # Refresh 60s before expiry
            self._token_expires_at = (
                time.time()
                + data.get("expires_in", 3600)
                - 60
            )
            self.logger.info(
                "Spotify token refreshed (expires_in=%s)",
                data.get("expires_in"),
            )
        except Exception as e:
            self.logger.error(
                "Failed to refresh Spotify token: %s", e
            )
            raise

    async def _ensure_token(self) -> None:
        """Ensure we have a valid token."""
        if (
            not self._access_token
            or time.time() >= self._token_expires_at
        ):
            await self._refresh_token()

    async def _api_get(
        self,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> dict:
        """Make authenticated GET request to Spotify."""
        await self._ensure_token()
        url = f"{SPOTIFY_API_BASE}/{endpoint}"
        response = await self._http.get(
            url,
            params=params,
            headers={
                "Authorization": (
                    f"Bearer {self._access_token}"
                )
            },
        )
        response.raise_for_status()
        return response.json()

    # ── Search ────────────────────────────────────────

    async def search(
        self,
        query: str,
        search_type: str = "track",
        limit: int = 5,
        market: str = "BR",
    ) -> List[Dict[str, Any]]:
        """
        Search Spotify.

        Args:
            query: Search query string
            search_type: track, artist, album, playlist
            limit: Max results (1-50)
            market: Market code (BR, US, IE, etc.)

        Returns:
            List of formatted results
        """
        data = await self._api_get(
            "search",
            params={
                "q": query,
                "type": search_type,
                "limit": limit,
                "market": market,
            },
        )

        results = []
        items_key = f"{search_type}s"
        items = data.get(items_key, {}).get("items", [])

        for item in items:
            if search_type == "track":
                results.append(self._format_track(item))
            elif search_type == "artist":
                results.append(
                    self._format_artist(item)
                )
            elif search_type == "album":
                results.append(self._format_album(item))
            elif search_type == "playlist":
                results.append(
                    self._format_playlist(item)
                )

        return results

    async def search_tracks(
        self, query: str, limit: int = 5
    ) -> List[Dict]:
        return await self.search(query, "track", limit)

    async def search_artists(
        self, query: str, limit: int = 5
    ) -> List[Dict]:
        return await self.search(query, "artist", limit)

    async def search_albums(
        self, query: str, limit: int = 5
    ) -> List[Dict]:
        return await self.search(query, "album", limit)

    # ── Get by ID ─────────────────────────────────────

    async def get_track(self, track_id: str) -> Dict:
        data = await self._api_get(f"tracks/{track_id}")
        return self._format_track(data)

    async def get_artist(self, artist_id: str) -> Dict:
        data = await self._api_get(
            f"artists/{artist_id}"
        )
        print(
            "[SPOTIFY DEBUG] FULL RAW RESPONSE "
            f"KEYS: {list(data.keys())}"
        )
        print(
            "[SPOTIFY DEBUG] FULL RAW RESPONSE: "
            f"{data}"
        )
        result = self._format_artist(data)
        return result

    async def get_artist_top_tracks(
        self,
        artist_name: str,
        limit: int = 10,
        market: str = "BR",
    ) -> List[Dict]:
        """Get top tracks for an artist via search.

        The /artists/{id}/top-tracks endpoint returns 403
        with Client Credentials flow, so we use search
        with ``artist:`` prefix instead.
        """
        return await self.search(
            query=f"artist:{artist_name}",
            search_type="track",
            limit=limit,
            market=market,
        )

    async def get_album(self, album_id: str) -> Dict:
        data = await self._api_get(f"albums/{album_id}")
        return self._format_album(data)

    # ── Recommendations ───────────────────────────────

    async def get_recommendations(
        self,
        seed_genres: Optional[List[str]] = None,
        seed_artists: Optional[List[str]] = None,
        limit: int = 5,
        market: str = "BR",
    ) -> List[Dict]:
        """Get music recommendations via search.

        The /recommendations endpoint returns 404
        with Client Credentials flow, so we simulate
        it with creative Spotify search queries.
        """
        if seed_genres:
            genre = seed_genres[0]
            return await self.search(
                query=f"genre:{genre}",
                search_type="track",
                limit=limit,
                market=market,
            )

        if seed_artists:
            artist = seed_artists[0]
            return await self.search(
                query=artist,
                search_type="track",
                limit=limit,
                market=market,
            )

        # Default: popular tracks
        return await self.search(
            query="genre:pop",
            search_type="track",
            limit=limit,
            market=market,
        )

    # ── Formatting Helpers ────────────────────────────

    @staticmethod
    def _format_track(track: dict) -> Dict:
        artists = ", ".join(
            a["name"] for a in track.get("artists", [])
        )
        album = track.get("album", {})
        duration_ms = track.get("duration_ms", 0)
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) // 1000

        return {
            "type": "track",
            "id": track.get("id", ""),
            "name": track.get("name", ""),
            "artists": artists,
            "album": album.get("name", ""),
            "album_image": (
                album.get("images", [{}])[0].get(
                    "url", ""
                )
                if album.get("images")
                else ""
            ),
            "duration": f"{minutes}:{seconds:02d}",
            "duration_ms": duration_ms,
            "popularity": track.get("popularity", 0),
            "preview_url": track.get("preview_url"),
            "spotify_url": track.get(
                "external_urls", {}
            ).get("spotify", ""),
            "uri": track.get("uri", ""),
        }

    @staticmethod
    def _format_artist(artist: dict) -> Dict:
        # followers can be: {"total": N}, int, or None
        followers_raw = artist.get("followers")
        if isinstance(followers_raw, dict):
            followers = followers_raw.get("total", 0)
        elif isinstance(followers_raw, (int, float)):
            followers = int(followers_raw)
        else:
            followers = 0

        return {
            "type": "artist",
            "id": artist.get("id", ""),
            "name": artist.get("name", ""),
            "genres": ", ".join(
                artist.get("genres", [])[:5]
            ),
            "popularity": artist.get(
                "popularity", 0
            )
            or 0,
            "followers": followers,
            "image": (
                artist.get("images", [{}])[0].get(
                    "url", ""
                )
                if artist.get("images")
                else ""
            ),
            "spotify_url": artist.get(
                "external_urls", {}
            ).get("spotify", ""),
            "uri": artist.get("uri", ""),
        }

    @staticmethod
    def _format_album(album: dict) -> Dict:
        artists = ", ".join(
            a["name"] for a in album.get("artists", [])
        )
        return {
            "type": "album",
            "id": album.get("id", ""),
            "name": album.get("name", ""),
            "artists": artists,
            "release_date": album.get(
                "release_date", ""
            ),
            "total_tracks": album.get(
                "total_tracks", 0
            ),
            "image": (
                album.get("images", [{}])[0].get(
                    "url", ""
                )
                if album.get("images")
                else ""
            ),
            "spotify_url": album.get(
                "external_urls", {}
            ).get("spotify", ""),
            "uri": album.get("uri", ""),
        }

    @staticmethod
    def _format_playlist(playlist: dict) -> Dict:
        owner = playlist.get("owner", {})
        return {
            "type": "playlist",
            "id": playlist.get("id", ""),
            "name": playlist.get("name", ""),
            "description": playlist.get(
                "description", ""
            ),
            "owner": owner.get("display_name", ""),
            "total_tracks": playlist.get(
                "tracks", {}
            ).get("total", 0),
            "image": (
                playlist.get("images", [{}])[0].get(
                    "url", ""
                )
                if playlist.get("images")
                else ""
            ),
            "spotify_url": playlist.get(
                "external_urls", {}
            ).get("spotify", ""),
        }
