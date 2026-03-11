"""
tests/test_spotify_service.py
==============================
Unit tests for SpotifyService.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.integrations.spotify_service import (
    SpotifyService,
)


@pytest.fixture
def spotify_service():
    with patch.dict(
        "os.environ",
        {
            "SPOTIFY_CLIENT_ID": "test_id",
            "SPOTIFY_CLIENT_SECRET": "test_secret",
        },
    ):
        svc = SpotifyService()
        # Give it a pre-set token so tests don't
        # need to hit the auth endpoint
        svc._access_token = "test_token"
        svc._token_expires_at = 9999999999
        svc._http = MagicMock()
        svc._initialized = True
        return svc


class TestSpotifyAuth:
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "test_token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(
            return_value=mock_response
        )

        with patch.dict(
            "os.environ",
            {
                "SPOTIFY_CLIENT_ID": "test_id",
                "SPOTIFY_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "httpx.AsyncClient",
                return_value=mock_http,
            ):
                svc = SpotifyService()
                await svc._initialize()
                assert svc._access_token == "test_token"

    @pytest.mark.asyncio
    async def test_initialize_no_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            svc = SpotifyService()
            await svc._initialize()
            assert svc._access_token is None

    @pytest.mark.asyncio
    async def test_token_refresh(self, spotify_service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        spotify_service._http.post = AsyncMock(
            return_value=mock_response
        )

        await spotify_service._refresh_token()
        assert (
            spotify_service._access_token == "new_token"
        )

    @pytest.mark.asyncio
    async def test_health_check_with_token(
        self, spotify_service
    ):
        result = await spotify_service._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_token(self):
        svc = SpotifyService()
        result = await svc._health_check()
        assert result is False


class TestSpotifySearch:
    @pytest.mark.asyncio
    async def test_search_tracks(self, spotify_service):
        mock_api_response = {
            "tracks": {
                "items": [
                    {
                        "id": "track1",
                        "name": "Bohemian Rhapsody",
                        "artists": [{"name": "Queen"}],
                        "album": {
                            "name": (
                                "A Night at the Opera"
                            ),
                            "images": [
                                {
                                    "url": (
                                        "https://img.com"
                                        "/album.jpg"
                                    )
                                }
                            ],
                        },
                        "duration_ms": 354000,
                        "popularity": 92,
                        "preview_url": (
                            "https://preview.url"
                        ),
                        "external_urls": {
                            "spotify": (
                                "https://open.spotify"
                                ".com/track/track1"
                            )
                        },
                        "uri": "spotify:track:track1",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_api_response
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = await spotify_service.search_tracks(
            "Bohemian Rhapsody"
        )
        assert len(results) == 1
        assert results[0]["name"] == "Bohemian Rhapsody"
        assert results[0]["artists"] == "Queen"
        assert results[0]["type"] == "track"

    @pytest.mark.asyncio
    async def test_search_artists(self, spotify_service):
        mock_api_response = {
            "artists": {
                "items": [
                    {
                        "id": "artist1",
                        "name": "Queen",
                        "genres": [
                            "rock",
                            "classic rock",
                        ],
                        "popularity": 89,
                        "followers": {
                            "total": 48000000
                        },
                        "images": [
                            {
                                "url": (
                                    "https://img.com"
                                    "/queen.jpg"
                                )
                            }
                        ],
                        "external_urls": {
                            "spotify": (
                                "https://open.spotify"
                                ".com/artist/artist1"
                            )
                        },
                        "uri": "spotify:artist:artist1",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_api_response
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = await spotify_service.search_artists(
            "Queen"
        )
        assert len(results) == 1
        assert results[0]["name"] == "Queen"
        assert results[0]["type"] == "artist"

    @pytest.mark.asyncio
    async def test_search_albums(self, spotify_service):
        mock_api_response = {
            "albums": {
                "items": [
                    {
                        "id": "al1",
                        "name": "Thriller",
                        "artists": [
                            {"name": "Michael Jackson"}
                        ],
                        "release_date": "1982-11-30",
                        "total_tracks": 9,
                        "images": [
                            {"url": "https://img.com/t"}
                        ],
                        "external_urls": {
                            "spotify": (
                                "https://open.spotify"
                                ".com/album/al1"
                            )
                        },
                        "uri": "spotify:album:al1",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_api_response
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = await spotify_service.search_albums(
            "Thriller"
        )
        assert len(results) == 1
        assert results[0]["name"] == "Thriller"
        assert results[0]["type"] == "album"

    @pytest.mark.asyncio
    async def test_search_empty_results(
        self, spotify_service
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tracks": {"items": []}
        }
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = await spotify_service.search_tracks(
            "nonexistent_xyzzy"
        )
        assert results == []


class TestSpotifyGetById:
    @pytest.mark.asyncio
    async def test_get_track(self, spotify_service):
        track_data = {
            "id": "t1",
            "name": "Song",
            "artists": [{"name": "Artist"}],
            "album": {
                "name": "Album",
                "images": [{"url": "img"}],
            },
            "duration_ms": 210000,
            "popularity": 80,
            "preview_url": None,
            "external_urls": {"spotify": "url"},
            "uri": "spotify:track:t1",
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = track_data
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        result = await spotify_service.get_track("t1")
        assert result["name"] == "Song"
        assert result["type"] == "track"

    @pytest.mark.asyncio
    async def test_get_artist(self, spotify_service):
        artist_data = {
            "id": "a1",
            "name": "Band",
            "genres": ["rock"],
            "popularity": 70,
            "followers": {"total": 500000},
            "images": [{"url": "img"}],
            "external_urls": {"spotify": "url"},
            "uri": "spotify:artist:a1",
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = artist_data
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        result = await spotify_service.get_artist("a1")
        assert result["name"] == "Band"
        assert result["type"] == "artist"

    @pytest.mark.asyncio
    async def test_get_artist_top_tracks(
        self, spotify_service
    ):
        """Top tracks now uses search with artist: prefix."""
        api_resp = {
            "tracks": {
                "items": [
                    {
                        "id": "t1",
                        "name": "Hit",
                        "artists": [{"name": "Band"}],
                        "album": {
                            "name": "Al",
                            "images": [],
                        },
                        "duration_ms": 180000,
                        "popularity": 90,
                        "preview_url": None,
                        "external_urls": {
                            "spotify": "url"
                        },
                        "uri": "spotify:track:t1",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = (
            await spotify_service.get_artist_top_tracks(
                "Band"
            )
        )
        assert len(results) == 1
        assert results[0]["name"] == "Hit"
        # Verify it searched with artist: prefix
        call_kwargs = (
            spotify_service._http.get.call_args
        )
        params = call_kwargs.kwargs.get("params", {})
        assert params["q"] == "artist:Band"
        assert params["type"] == "track"


class TestRecommendations:
    @pytest.mark.asyncio
    async def test_recommendations_with_genre(
        self, spotify_service
    ):
        """Recommendations with genre uses search."""
        api_resp = {
            "tracks": {
                "items": [
                    {
                        "id": "r1",
                        "name": "Rec Song",
                        "artists": [{"name": "DJ"}],
                        "album": {
                            "name": "Mix",
                            "images": [],
                        },
                        "duration_ms": 200000,
                        "popularity": 60,
                        "preview_url": None,
                        "external_urls": {
                            "spotify": "url"
                        },
                        "uri": "spotify:track:r1",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = (
            await spotify_service.get_recommendations(
                seed_genres=["rock"]
            )
        )
        assert len(results) == 1
        assert results[0]["name"] == "Rec Song"
        # Verify it searched with genre: prefix
        call_kwargs = (
            spotify_service._http.get.call_args
        )
        params = call_kwargs.kwargs.get("params", {})
        assert params["q"] == "genre:rock"

    @pytest.mark.asyncio
    async def test_recommendations_with_artist(
        self, spotify_service
    ):
        """Recommendations with artist seeds."""
        api_resp = {
            "tracks": {
                "items": [
                    {
                        "id": "r2",
                        "name": "Artist Rec",
                        "artists": [{"name": "DJ"}],
                        "album": {
                            "name": "Mix",
                            "images": [],
                        },
                        "duration_ms": 200000,
                        "popularity": 50,
                        "preview_url": None,
                        "external_urls": {
                            "spotify": "url"
                        },
                        "uri": "spotify:track:r2",
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = (
            await spotify_service.get_recommendations(
                seed_artists=["Eminem"]
            )
        )
        assert len(results) == 1
        call_kwargs = (
            spotify_service._http.get.call_args
        )
        params = call_kwargs.kwargs.get("params", {})
        assert params["q"] == "Eminem"

    @pytest.mark.asyncio
    async def test_recommendations_default(
        self, spotify_service
    ):
        """Default recommendations search genre:pop."""
        api_resp = {"tracks": {"items": []}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_resp
        mock_resp.raise_for_status = MagicMock()
        spotify_service._http.get = AsyncMock(
            return_value=mock_resp
        )

        results = (
            await spotify_service.get_recommendations()
        )
        assert results == []
        # Should have used genre:pop default
        call_kwargs = (
            spotify_service._http.get.call_args
        )
        params = call_kwargs.kwargs.get("params", {})
        assert params["q"] == "genre:pop"


class TestFormatting:
    def test_format_track(self):
        track = {
            "id": "t1",
            "name": "Song",
            "artists": [{"name": "Artist"}],
            "album": {
                "name": "Album",
                "images": [{"url": "img"}],
            },
            "duration_ms": 210000,
            "popularity": 80,
            "preview_url": None,
            "external_urls": {"spotify": "url"},
            "uri": "spotify:track:t1",
        }
        result = SpotifyService._format_track(track)
        assert result["name"] == "Song"
        assert result["duration"] == "3:30"
        assert result["type"] == "track"

    def test_format_artist(self):
        artist = {
            "id": "a1",
            "name": "Artist",
            "genres": ["pop", "rock"],
            "popularity": 75,
            "followers": {"total": 1000000},
            "images": [{"url": "img"}],
            "external_urls": {"spotify": "url"},
            "uri": "spotify:artist:a1",
        }
        result = SpotifyService._format_artist(artist)
        assert result["name"] == "Artist"
        assert result["genres"] == "pop, rock"
        assert result["followers"] == 1000000

    def test_format_artist_followers_null(self):
        """Handle followers: null from Spotify API."""
        artist = {
            "id": "a1",
            "name": "X",
            "genres": [],
            "popularity": None,
            "followers": None,
            "images": [],
            "external_urls": {"spotify": ""},
            "uri": "",
        }
        result = SpotifyService._format_artist(artist)
        assert result["followers"] == 0
        assert result["popularity"] == 0

    def test_format_artist_followers_int(self):
        """Handle already-formatted followers as int."""
        artist = {
            "id": "a1",
            "name": "X",
            "genres": [],
            "popularity": 80,
            "followers": 5000000,
            "images": [],
            "external_urls": {"spotify": ""},
            "uri": "",
        }
        result = SpotifyService._format_artist(artist)
        assert result["followers"] == 5000000

    def test_format_album(self):
        album = {
            "id": "al1",
            "name": "Album",
            "artists": [{"name": "Artist"}],
            "release_date": "2024-01-01",
            "total_tracks": 12,
            "images": [{"url": "img"}],
            "external_urls": {"spotify": "url"},
            "uri": "spotify:album:al1",
        }
        result = SpotifyService._format_album(album)
        assert result["name"] == "Album"
        assert result["total_tracks"] == 12

    def test_format_track_no_images(self):
        track = {
            "id": "t1",
            "name": "Song",
            "artists": [{"name": "A"}],
            "album": {"name": "Al", "images": []},
            "duration_ms": 0,
            "popularity": 0,
            "preview_url": None,
            "external_urls": {"spotify": ""},
            "uri": "",
        }
        result = SpotifyService._format_track(track)
        assert result["album_image"] == ""
        assert result["duration"] == "0:00"

    def test_format_playlist(self):
        playlist = {
            "id": "p1",
            "name": "My Playlist",
            "description": "Cool songs",
            "owner": {"display_name": "user1"},
            "tracks": {"total": 25},
            "images": [{"url": "img"}],
            "external_urls": {"spotify": "url"},
        }
        result = SpotifyService._format_playlist(
            playlist
        )
        assert result["name"] == "My Playlist"
        assert result["total_tracks"] == 25
        assert result["type"] == "playlist"
